import json
import os
import requests
import xml.etree.ElementTree as ET
import jsbeautifier
import difflib
from typing import Dict

# ==================== Load config ====================
with open('config.json') as f:
    config = json.load(f)

INSTANCE1 = config['instances']['instance1']
INSTANCE2 = config['instances']['instance2']
TABLES = config['tables']
QUERY = config['query']
OUTPUT_DIR = config['output_dir']

# ==================== Helper Functions ====================

def get_records(host: str, user: str, password: str, table: str, query: str):
    url = f"https://{host}.service-now.com/api/now/table/{table}"
    resp = requests.get(url, auth=(user, password), params={"sysparm_query": query, "sysparm_limit": "1000"})
    resp.raise_for_status()
    return resp.json().get('result', [])

def fetch_xml(host: str, table: str, sys_id: str, user: str, password: str) -> ET.Element:
    url = f"https://{host}.service-now.com/{table}.do?XML&sys_id={sys_id}"
    resp = requests.get(url, auth=(user, password))
    resp.raise_for_status()
    return ET.fromstring(resp.content)

def extract_all_tags(root: ET.Element) -> Dict[str, str]:
    record_node = list(root)[0]
    result = {}
    for child in record_node:
        text = child.text or ""
        if "script" in child.tag.lower():  # beautify JS scripts
            text = jsbeautifier.beautify(text, jsbeautifier.default_options())
        result[child.tag] = text
    return result

def generate_side_by_side_diff_html(text1: str, text2: str) -> str:
    differ = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)
    diff_table = differ.make_table(
        text1.splitlines(),
        text2.splitlines(),
        fromdesc='Instance1',
        todesc='Instance2',
        context=False
    )
    style = """
    <style>
    table.diff {font-family: monospace; font-size: 0.8rem; border-collapse: collapse; width: 100%;}
    .diff_add {background-color: #d4fcbc;} 
    .diff_chg {background-color: #fff3bf;} 
    .diff_sub {background-color: #fbb6b6;} 
    </style>
    """
    return style + diff_table

# ==================== HTML Report Builder ====================

def wrap_html_report(all_sections_html: str, summary_html: str) -> str:
    return f"""<!DOCTYPE html><html><head><title>Comparison Report</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
<style>
.status-highlight {{background:#fdecea !important; color:#d9534f; font-weight:bold;}}
.modal-xl {{max-width: 95% !important;}}
</style></head><body class="p-3">
<h1>Comparison Report</h1>
{summary_html}
<hr>
{all_sections_html}
<script>
function filterDetailRows(recordId, filterType) {{
  let selector = recordId ? `#record-${{recordId}} table tbody tr` : 'div[id^="record-"] table tbody tr';
  document.querySelectorAll(selector).forEach(tr => {{
    const status = tr.getAttribute('data-status');
    if (filterType === 'changed') {{
      tr.style.display = (status !== 'unchanged') ? '' : 'none';
    }} else if (filterType === 'unchanged') {{
      tr.style.display = (status === 'unchanged') ? '' : 'none';
    }} else {{
      tr.style.display = '';
    }}
  }});
}}
function openModal(id) {{
  new bootstrap.Modal(document.getElementById(id)).show();
}}
</script>
</body></html>"""

def generate_summary_html(summary_data):
    # summary_data is list of tuples: (table_name, record_name, diff_count)
    summary_rows = ""
    for table_name, record_name, diff_count in summary_data:
        highlight_class = "table-danger" if diff_count > 0 else "table-success"
        summary_rows += f"""
<tr class="{highlight_class}">
  <td>{table_name}</td><td>{record_name}</td><td>{diff_count}</td>
</tr>"""
    return f"""<h2>Summary</h2>
<table class="table table-bordered table-sm"><thead><tr><th>Table</th><th>Record</th><th>Diffs</th></tr></thead><tbody>{summary_rows}</tbody></table>"""

def generate_detail_table(data1, data2, record_name):
    all_keys = sorted(set(data1.keys()) | set(data2.keys()))
    record_id = record_name.replace(' ', '_').replace('.', '_')
    detail_rows = ""
    diff_count = 0
    for key in all_keys:
        val1, val2 = data1.get(key, ""), data2.get(key, "")
        status = "Unchanged"
        if val1 != val2:
            status = "Changed"
        if not val1 and val2:
            status = "Added"
        elif val1 and not val2:
            status = "Removed"
        status_class = "status-highlight" if status != "Unchanged" else ""
        if "script" in key.lower() and val1 != val2:
            diff_table = generate_side_by_side_diff_html(val1, val2)
            popup_id = f"{record_id}_{key}"
            detail_rows += f"""
<tr data-status="{status.lower()}"><td>{key}</td><td colspan="2">
<button class="btn btn-sm btn-primary" onclick="openModal('{popup_id}')">View Diff</button>
<div class="modal fade" id="{popup_id}" tabindex="-1"><div class="modal-dialog modal-xl"><div class="modal-content"><div class="modal-body">{diff_table}</div></div></div></div></td><td class="{status_class}">{status}</td></tr>"""
        else:
            detail_rows += f"""
<tr data-status="{status.lower()}"><td>{key}</td><td>{val1}</td><td>{val2}</td><td class="{status_class}">{status}</td></tr>"""
        if status != "Unchanged":
            diff_count += 1
    return diff_count, f"""
<div id="record-{record_id}" class="mb-4"><h3>{record_name}</h3>
<button class="btn btn-sm btn-primary" onclick="filterDetailRows('record-{record_id}', 'all')">All</button>
<button class="btn btn-sm btn-success" onclick="filterDetailRows('record-{record_id}', 'changed')">Changed</button>
<button class="btn btn-sm btn-secondary" onclick="filterDetailRows('record-{record_id}', 'unchanged')">Unchanged</button>
<table class="table table-bordered table-sm"><thead><tr><th>Field</th><th>Instance1</th><th>Instance2</th><th>Status</th></tr></thead><tbody>{detail_rows}</tbody></table></div>"""

# ==================== Main Entry ====================

def main():
    summary_data = []
    sections_html = []
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for table in TABLES:
        print(f"[INFO] Processing {table}")
        records = get_records(INSTANCE1['host'], INSTANCE1['user'], INSTANCE1['pass'], table, QUERY)
        for record in records:
            record_name = record.get('name') or record.get('short_description') or record['sys_id']
            sys_id = record['sys_id']
            data1 = extract_all_tags(fetch_xml(INSTANCE1['host'], table, sys_id, INSTANCE1['user'], INSTANCE1['pass']))
            data2 = extract_all_tags(fetch_xml(INSTANCE2['host'], table, sys_id, INSTANCE2['user'], INSTANCE2['pass']))
            diff_count, table_html = generate_detail_table(data1, data2, record_name)
            summary_data.append((table, record_name, diff_count))
            sections_html.append(table_html)

    summary_html = generate_summary_html(summary_data)
    report_html = wrap_html_report("\n".join(sections_html), summary_html)
    output_path = os.path.join(OUTPUT_DIR, "comparison_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"[✅] Report saved to: {output_path}")

if __name__ == "__main__":
    main()
