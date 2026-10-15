import html
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from minio import Minio
from minio.error import S3Error

REPORT_PREFIX = 'reports/'


def report_key(log_name):
    return f"{REPORT_PREFIX}{log_name}.html"


class Handler(BaseHTTPRequestHandler):
    # Set in main()
    client = None
    bucket = None
    log_prefix = ''

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/':
            self.show_logs(parse_qs(url.query).get('error', [''])[0])
        elif url.path == '/report':
            self.show_report(parse_qs(url.query).get('log', [''])[0])
        else:
            self.send_text(404, 'Not found')

    def do_POST(self):
        if urlparse(self.path).path != '/generate':
            return self.send_text(404, 'Not found')
        length = int(self.headers.get('Content-Length', 0))
        form = parse_qs(self.rfile.read(length).decode())
        log_name = form.get('log', [''])[0]
        if not self.log_exists(log_name):
            return self.send_text(404, 'Unknown log')
        error = self.generate_report(log_name)
        self.redirect('/' + (f"?error={quote(error)}" if error else ''))

    def log_exists(self, name):
        if not name.endswith('.log') or not name.startswith(self.log_prefix):
            return False
        try:
            self.client.stat_object(self.bucket, name)
        except S3Error:
            return False
        return True

    def generate_report(self, log_name):
        """Analyse the log and store the report in MinIO. Returns an error message or None."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, os.path.basename(log_name))
            out_path = os.path.join(tmp, 'report.html')
            self.client.fget_object(self.bucket, log_name, log_path)
            result = subprocess.run(['mysql-badger', '-f', log_path, '-o', out_path])
            if result.returncode != 0 or not os.path.exists(out_path):
                return f"Could not generate a report for {log_name} (no queries found?)"
            self.client.fput_object(self.bucket, report_key(log_name), out_path,
                                    content_type='text/html')

    def show_report(self, log_name):
        if not self.log_exists(log_name):
            return self.send_text(404, 'Unknown log')
        try:
            response = self.client.get_object(self.bucket, report_key(log_name))
        except S3Error:
            return self.send_text(404, 'Report not generated yet')
        try:
            self.send_body(200, response.read(), 'text/html; charset=utf-8')
        finally:
            response.close()
            response.release_conn()

    def show_logs(self, error):
        reports = {o.object_name: o for o in
                   self.client.list_objects(self.bucket, prefix=REPORT_PREFIX, recursive=True)}
        logs = [o for o in self.client.list_objects(self.bucket, prefix=self.log_prefix, recursive=True)
                if o.object_name.endswith('.log')]

        rows = []
        for obj in logs:
            name = obj.object_name
            report = reports.get(report_key(name))
            if report:
                status = (f'<a href="/report?log={html.escape(quote(name))}">View report</a> '
                          f'<small>({report.last_modified:%Y-%m-%d %H:%M})</small>')
                label = 'Regenerate'
            else:
                status, label = 'Not generated', 'Generate'
            rows.append(
                f'<tr><td>{html.escape(name)}</td><td>{obj.size:,}</td>'
                f'<td>{obj.last_modified:%Y-%m-%d %H:%M}</td><td>{status}</td>'
                f'<td><form method="post" action="/generate">'
                f'<input type="hidden" name="log" value="{html.escape(name)}">'
                f'<button>{label}</button></form></td></tr>')

        body = (
            '<!doctype html><meta charset="utf-8"><title>MySQL Badger</title>'
            '<style>body{font-family:sans-serif;margin:2rem}td,th{padding:.4rem .8rem;text-align:left}'
            '.error{color:#b00}</style><h1>Slow query logs</h1>'
            + (f'<p class="error">{html.escape(error)}</p>' if error else '')
            + '<table><tr><th>Log</th><th>Bytes</th><th>Modified</th><th>Report</th><th></th></tr>'
            + ''.join(rows) + '</table>'
            + ('' if rows else '<p>No .log files found in the bucket.</p>'))
        self.send_body(200, body.encode(), 'text/html; charset=utf-8')

    def redirect(self, location):
        self.send_response(303)
        self.send_header('Location', location)
        self.end_headers()

    def send_text(self, status, text):
        self.send_body(status, text.encode(), 'text/plain; charset=utf-8')

    def send_body(self, status, data, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    client = Minio(
        os.environ['MINIO_ENDPOINT'],
        access_key=os.environ['MINIO_ACCESS_KEY'],
        secret_key=os.environ['MINIO_SECRET_KEY'],
        secure=os.environ.get('MINIO_SECURE', 'false').lower() == 'true',
    )
    bucket = os.environ['MINIO_BUCKET']
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    Handler.client = client
    Handler.bucket = bucket
    Handler.log_prefix = os.environ.get('MINIO_PREFIX', '')

    port = int(os.environ.get('PORT', '8080'))
    print(f"Serving on port {port}")
    ThreadingHTTPServer(('', port), Handler).serve_forever()


if __name__ == '__main__':
    main()
