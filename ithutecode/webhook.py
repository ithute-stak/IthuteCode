"""Minimal WSGI ingress; deploy behind TLS and a production WSGI server."""
from .github_events import authenticate_notice

def application(inbox, secret, allowed_repositories):
    if not isinstance(secret, bytes) or not secret or not allowed_repositories:
        raise ValueError("Webhook secret and repository allowlist required")
    def app(environ, start_response):
        def respond(status, body):
            start_response(status, [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
            return [body]
        if environ.get("PATH_INFO") != "/webhooks/github":
            return respond("404 Not Found", b"not found")
        if environ.get("REQUEST_METHOD") != "POST":
            return respond("405 Method Not Allowed", b"method not allowed")
        try:
            size = int(environ.get("CONTENT_LENGTH") or "-1")
            if not 0 <= size <= 2_000_000:
                return respond("400 Bad Request", b"invalid content length")
            body = environ["wsgi.input"].read(size)
            if len(body) != size:
                return respond("400 Bad Request", b"incomplete body")
            notice = authenticate_notice(body, environ.get("HTTP_X_HUB_SIGNATURE_256", ""),
                        environ.get("HTTP_X_GITHUB_EVENT", ""), secret, allowed_repositories)
            if notice is not None:
                inbox.enqueue(environ.get("HTTP_X_GITHUB_DELIVERY", ""), notice)
        except PermissionError:
            return respond("403 Forbidden", b"forbidden")
        except (ValueError, TypeError, KeyError, AttributeError):
            return respond("400 Bad Request", b"invalid payload")
        return respond("202 Accepted", b"accepted")
    return app
