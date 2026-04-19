✅ Сервер запущен: http://localhost:8080
127.0.0.1 - - [11/Feb/2026 03:46:44] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [11/Feb/2026 03:46:44] "GET /favicon.ico HTTP/1.1" 200 -
127.0.0.1 - - [11/Feb/2026 03:47:06] "POST /gen HTTP/1.1" 200 -
127.0.0.1 - - [11/Feb/2026 03:47:06] "GET /favicon.ico HTTP/1.1" 200 -
Traceback (most recent call last):
  File "c:\Users\snltv\Desktop\ii\putevoi list\путевой лист финал!!11-02-2026.py", line 126, in <module>
    if __name__ == "__main__": main()
                               ~~~~^^
  File "c:\Users\snltv\Desktop\ii\putevoi list\путевой лист финал!!11-02-2026.py", line 124, in main
    HTTPServer(('localhost', PORT), Handler).serve_forever()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "C:\Users\snltv\AppData\Local\Programs\Python\Python313\Lib\socketserver.py", line 235, in serve_forever
    ready = selector.select(poll_interval)
  File "C:\Users\snltv\AppData\Local\Programs\Python\Python313\Lib\selectors.py", line 314, in select
    r, w, _ = self._select(self._readers, self._writers, [], timeout)
              ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\snltv\AppData\Local\Programs\Python\Python313\Lib\selectors.py", line 305, in _select
    r, w, x = select.select(r, w, w, timeout)
              ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
KeyboardInterrupt