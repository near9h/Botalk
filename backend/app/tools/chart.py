"""Chart tool -- build a self-contained ECharts HTML snippet.

The result is wrapped in a fenced `echarts-html` block so the frontend can
detect it and render it inside a sandboxed iframe (rather than trusting raw
HTML in the markdown renderer).
"""
from __future__ import annotations

import json

_CHART_TYPES = {"bar", "line", "pie", "scatter"}


def generate_chart(args: dict, config: dict | None = None) -> str:
    spec = args.get("spec")
    if not isinstance(spec, dict):
        return "[工具错误] generate_chart 缺少 spec 对象"

    chart_type = str(spec.get("chartType") or spec.get("type") or "bar").lower()
    if chart_type not in _CHART_TYPES:
        chart_type = "bar"

    title = str(spec.get("title") or "图表")
    labels = spec.get("labels") or []
    series = spec.get("series") or []

    if chart_type == "pie":
        option = _pie_option(title, labels, series)
    else:
        option = _cartesian_option(title, labels, series, chart_type)

    html = _render_html(title, option)
    # Fence with a custom language so the frontend can intercept it safely.
    return f"```echarts-html\n{html}\n```"


def _cartesian_option(title: str, labels: list, series: list, chart_type: str) -> dict:
    series_out = []
    for s in series:
        if not isinstance(s, dict):
            continue
        series_out.append(
            {
                "name": str(s.get("name") or ""),
                "type": chart_type,
                "data": s.get("data") or [],
            }
        )
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0} if series_out else {},
        "xAxis": {"type": "category", "data": list(labels)},
        "yAxis": {"type": "value"},
        "series": series_out,
    }


def _pie_option(title: str, labels: list, series: list) -> dict:
    data = []
    if series and isinstance(series[0], dict):
        values = series[0].get("data") or []
        for i, v in enumerate(values):
            name = labels[i] if i < len(labels) else f"项{i + 1}"
            data.append({"name": str(name), "value": v})
    else:
        for i, v in enumerate(labels):
            data.append({"name": str(v), "value": 1})
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 0},
        "series": [{"type": "pie", "radius": "55%", "data": data}],
    }


def _render_html(title: str, option: dict) -> str:
    option_json = json.dumps(option, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>html,body,#chart{{margin:0;height:100%;width:100%}}</style>
</head>
<body>
<div id="chart"></div>
<script>
(function(){{
  var el = document.getElementById('chart');
  var chart = echarts.init(el);
  chart.setOption({option_json});
  window.addEventListener('resize', function(){{ chart.resize(); }});
}})();
</script>
</body>
</html>"""
