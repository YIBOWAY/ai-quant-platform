module.exports = new Proxy(
  {},
  {
    get() {
      return "@font-face { font-family: 'LocalBuildMock'; font-style: normal; font-weight: 100 900; src: url(mock-font.woff2) format('woff2'); }";
    },
  },
);
