from __future__ import annotations

import httpx

from . import net


def send_ntfy(cfg: dict, rows) -> bool:
    topic = cfg.get("topic")
    if not topic or not rows:
        return False
    top = rows[:8]
    lines = [f"[{r['category']}] {r['title']} @ {r['company']} ({r['score']})" for r in top]
    if len(rows) > len(top):
        lines.append(f"... e altri {len(rows) - len(top)}")
    try:
        with net.client(timeout=10) as c:
            c.post(
                f"{cfg.get('server', 'https://ntfy.sh')}/{topic}",
                content="\n".join(lines).encode(),
                headers={
                    "Title": f"JobsHunter: {len(rows)} nuovi annunci".encode(),
                    "Click": top[0]["url"],
                    "Tags": "briefcase",
                },
            ).raise_for_status()
        return True
    except httpx.HTTPError:
        return False
