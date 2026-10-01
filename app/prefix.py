from werkzeug.wrappers import Response


class PrefixMiddleware:
    def __init__(self, app, prefix):
        self.app, self.prefix = app, prefix

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == self.prefix:
            return Response('',302,{'Location':self.prefix+'/'})(environ,start_response)
        if not path.startswith(self.prefix+'/'):
            return Response('Not found',404)(environ,start_response)
        environ['SCRIPT_NAME'] = self.prefix
        environ['PATH_INFO'] = path[len(self.prefix):]
        return self.app(environ,start_response)
