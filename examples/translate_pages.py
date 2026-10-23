"""Translate selected pages through the local reader; API keys stay on the backend."""
import argparse
import json
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paper_id")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--max-cost", type=float, default=0.5, help="Maximum CNY reservation")
    parser.add_argument("--model", choices=["deepseek-flash", "deepseek-v4-pro"], default="deepseek-flash")
    parser.add_argument("--reasoning-effort", choices=["none", "low", "high", "max"], default="none")
    parser.add_argument("--run", action="store_true", help="Start the paid translation after estimation")
    args = parser.parse_args()
    end = args.end if args.end is not None else args.start
    if args.start < 1 or end < args.start or end - args.start >= 500:
        parser.error("Invalid page range (maximum 500 pages)")

    def api(path, body=None):
        request = Request(args.base.rstrip("/") + path,
                          data=json.dumps(body).encode("utf-8") if body is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    quote = api(f"/api/papers/{args.paper_id}/translations/estimate", {"pages": list(range(args.start, end + 1)), "model": args.model, "reasoning_effort": args.reasoning_effort})
    print(json.dumps({key: quote[key] for key in ("model", "reasoning_effort", "estimated_cny", "upper_bound_cny", "cached_pages", "total_pages")}, ensure_ascii=False, indent=2))
    if not args.run:
        print("Estimate only. Add --run to start translation.")
        return
    if quote["upper_bound_cny"] > args.max_cost:
        parser.error("Estimated upper bound exceeds --max-cost; no translation started")
    job = api(f"/api/papers/{args.paper_id}/translations", {"quote_id": quote["quote_id"], "max_cost_cny": args.max_cost})
    while job["status"] in {"queued", "running", "cancelling"}:
        print(f"{job['status']}: {job['completed_pages']}/{job['total_pages']}")
        time.sleep(2)
        job = api(f"/api/translation/jobs/{job['id']}")
    print(json.dumps(job, ensure_ascii=False, indent=2))
    if job["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
