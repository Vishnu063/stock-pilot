"""OpenAlgo status only. There is deliberately no broker-order function."""
import ipaddress
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def openalgo_status():
    base = os.environ.get("OPENALGO_URL", "http://127.0.0.1:5000").rstrip("/")
    parsed = urlsplit(base)
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a base URL without credentials, query or fragment")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("Remote OpenAlgo requires HTTPS")
    key = os.environ.get("OPENALGO_API_KEY")
    if not key:
        raise ValueError("Set OPENALGO_API_KEY in your shell")
    request = Request(base + "/api/v1/analyzer", data=json.dumps({"apikey":key}).encode(), headers={"Content-Type":"application/json"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        body = json.load(response)
    data = body.get("data", body)
    if body.get("status") != "success" or data.get("analyze_mode") is not True:
        raise ValueError("Analyzer mode could not be confirmed; do not route test orders")
    return {"connected":True,"analyzer_mode":True,"order_submission_implemented":False}


def performance_report(csv_path, output):
    import pandas as pd
    import quantstats as qs
    data = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date")
    if not data.index.is_unique or not data.index.is_monotonic_increasing:
        raise ValueError("Return dates must be unique and sorted")
    if data.empty or "return" not in data or data["return"].isna().any():
        raise ValueError("CSV requires date,return columns with net periodic returns")
    import math
    if not all(math.isfinite(float(v)) and float(v) >= -1 for v in data["return"]):
        raise ValueError("Returns must be finite and no less than -1")
    benchmark = data["benchmark"] if "benchmark" in data else None
    qs.reports.html(data["return"], benchmark=benchmark, output=output, title="Stock Pilot — supplied net returns")
    return {"report":output,"note":"Input returns must already include fees and slippage"}
