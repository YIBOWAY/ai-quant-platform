// Zero-dependency static server for the redesign demo.
// Accepts --port/--host CLI args and PORT/HOST env; defaults to 7100/127.0.0.1.
const http = require("http");
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
function argVal(name, dflt) {
  const i = args.indexOf(name);
  if (i !== -1 && args[i + 1]) return args[i + 1];
  const eq = args.find((a) => a.startsWith(name + "="));
  if (eq) return eq.split("=")[1];
  return dflt;
}
const port = Number(argVal("--port", process.env.PORT || 7100));
const host = argVal("--host", process.env.HOST || "127.0.0.1");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json",
};

http
  .createServer((req, res) => {
    let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    if (urlPath === "/") urlPath = "/index.html";
    const file = path.join(__dirname, path.normalize(urlPath));
    if (!file.startsWith(__dirname)) {
      res.writeHead(403);
      return res.end("forbidden");
    }
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404);
        return res.end("not found");
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
      res.end(data);
    });
  })
  .listen(port, host, () => console.log(`demo: http://${host}:${port}/`));
