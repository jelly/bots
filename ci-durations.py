#!/usr/bin/env python3

import asyncio
import re
import sys

import httpx

from lib.aio.github import GitHub
from lib.aio.jsonutil import get_dict, get_str, typechecked


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <PR-number>", file=sys.stderr)
        sys.exit(1)

    pr = int(sys.argv[1])
    repo = "cockpit-project/cockpit"

    config = {
        'api-url': 'https://api.github.com/',
        'clone-url': 'https://github.com/',
        'post': False,
        'user-agent': 'ci-durations (cockpit-project/cockpit)',
    }

    async with GitHub('github', config) as api:
        pull = await api.get_obj(f'repos/{repo}/pulls/{pr}')
        sha = get_str(get_dict(pull, 'head'), 'sha')

        statuses = typechecked(await api.get(f'repos/{repo}/statuses/{sha}', {'per_page': '100'}), list)

        # Dedupe by context (keep first = latest)
        latest: dict[str, dict] = {}
        for s in statuses:
            s = typechecked(s, dict)
            ctx = get_str(s, 'context')
            if ctx not in latest:
                latest[ctx] = s

        # Fetch log files and extract durations
        async def fetch_duration(ctx: str, s: dict) -> tuple[str, int | None, str]:
            state = get_str(s, 'state')
            url = get_str(s, 'target_url', None)
            if not url:
                return (ctx, None, state)
            log_url = url.replace('/log.html', '/log')
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(log_url, timeout=30)
                    matches = re.findall(r'# TESTS PASSED \[(\d+)s on', r.text)
                    if matches:
                        return (ctx, int(matches[-1]), state)
            except Exception:
                pass
            return (ctx, None, state)

        results = await asyncio.gather(*(fetch_duration(ctx, s) for ctx, s in latest.items()))

    results = sorted(results, key=lambda x: -(x[1] or 0))

    print(f"{'Image/Scenario':<45} {'Duration':>10}  State")
    print("-" * 70)
    for ctx, dur, state in results:
        dur_str = f"{dur}s" if dur is not None else "?"
        flag = " FAIL" if state == "failure" else ""
        print(f"{ctx:<45} {dur_str:>10}{flag}")


if __name__ == '__main__':
    asyncio.run(main())
