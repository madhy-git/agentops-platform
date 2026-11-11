// Starts Swagger UI for the AgentOps API (see index.html for why this isn't an inline script).
//
// The API lives behind nginx at /api, but its OpenAPI paths are written from the API's own point of view
// ("/triage", "/cases/{case_id}"). The request interceptor adds the /api prefix to "Try it out" calls, so they
// reach the API through the same proxy the web app uses.
window.ui = SwaggerUIBundle({
  url: "/openapi.json",
  dom_id: "#swagger-ui",
  deepLinking: true,
  persistAuthorization: false, // don't keep pasted tokens in localStorage
  requestInterceptor: (req) => {
    const u = new URL(req.url, window.location.origin);
    if (u.origin === window.location.origin && !u.pathname.startsWith("/api/") && u.pathname !== "/openapi.json") {
      u.pathname = "/api" + u.pathname;
      req.url = u.toString();
    }
    return req;
  },
});
