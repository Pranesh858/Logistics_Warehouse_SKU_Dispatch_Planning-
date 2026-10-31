"""python -m fake_systems --port 9100 --app-url http://localhost:8000 --app-key demo-key"""
import argparse

import uvicorn

from fake_systems import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="A fake WMS (/wms) and ERP (/erp) for the dispatch planner.")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to be reachable from other machines or containers")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--wms-key", default="wms-key", help="API key the planner must send to the WMS")
    ap.add_argument("--erp-key", default="erp-key", help="API key the planner must send to the ERP")
    ap.add_argument("--app-url", default="http://localhost:8000", help="the planner, for webhook pushes")
    ap.add_argument("--app-key", default="", help="the planner's INTEGRATION_WEBHOOK_KEY")
    ap.add_argument("--sales-days", type=int, default=1, help="closed days of sales the ERP returns per request")
    args = ap.parse_args()
    app = create_app(wms_key=args.wms_key, erp_key=args.erp_key, app_url=args.app_url,
                     app_webhook_key=args.app_key, sales_days=args.sales_days)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
