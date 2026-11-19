---
title: API mocks
description: Serve any API in the APIs.guru catalog as a mock with Prism — no real calls to the real API.
---

Any API in the [APIs.guru](https://apis.guru) catalog (2,529 APIs) can be served as a mock, with no real calls to the real API. Requires Node 18+ and Prism (`npm i -g @stoplight/prism-cli`); the spec is downloaded once and cached under `~/.cache/simwork`.

## Serve a mock

```bash
# Serve the httpbin API as a mock (prints the base URL to point at)
simwork mock --api httpbin.org --port 8124
# API_BASE_URL=http://127.0.0.1:8124

# With the stateful stub layer: writes are remembered, so create-then-read
# returns the created record (Prism alone is stateless)
simwork mock --api httpbin.org --port 8124 --stateful
```

`simwork mock` fetches the API's OpenAPI spec from APIs.guru (its preferred version is used) and serves it with Prism as a sidecar. It runs until Ctrl-C. Only the APIs actually touched run; the rest stay in the catalog.

## What Prism mocks — and what it does not

Prism mocks the *shape* of an API from its spec: routes, status codes, and example-shaped responses. It does not implement the API's real behaviour — no auth, no rate limits, no business logic — and specs in the catalog can be outdated. SimWork adds the state layer for the behaviour that matters most in tests (below), but a mock is still a shape, not the real service.

## Stateful stubs

Prism alone is stateless, so SimWork adds a state layer (`simwork.stateful`): a small proxy in front of Prism that remembers JSON writes per collection path. A `POST` stores the record (assigning a sequential `id` when the body has none) and answers `201`; a later `GET` on the collection returns the stored list and `GET <collection>/<id>` returns the stored record; `PUT`/`PATCH`/`DELETE` update or remove it. Reads on paths with nothing stored forward to Prism unchanged, so its example/schema behaviour is preserved. State is in-memory per process — restarting the mock resets the world, which keeps runs deterministic.

Enable it with `--stateful`. The demo's world API works the same way (a bundled ticket spec served through Prism).

## Fail closed

An unknown API name, a download failure, a missing `prism` binary, or a Prism process that exits early all fail closed with a visible error instead of falling back to the real API.

Only catalog APIs are served by name today — there is no `--spec` flag yet for a user's own OpenAPI file.
