# pyhanasu

[Hanasu](https://github.com/jsa-aerial/hanasu) for Python

Currently only supports the client side. However, by the design of Hanasu, the server and client are nearly symmetric. The exception being, servers open a websocket webserver port, while clients open connections to such ports.

The current version uses [trio](https://github.com/python-trio/trio) and [trio-websocket](https://github.com/HyperionGray/trio-websocket) for underlying infrastructure support.  While still not as flexible and capable as the Clojure(Script) version, the new Trio based implementation has produced significant improvements over the previous [asyncio](https://github.com/python/asyncio/wiki) version. In particular, it is simpler, easier to use and more robust.

For rationale and documentation of the API see the original Clojure(Script) version: [Hanasu](https://github.com/jsa-aerial/hanasu)
