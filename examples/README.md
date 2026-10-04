The executable examples live in `../dummy-servers/`: `bootstrap.mjs` initializes
before dynamic application imports; `http-services.mjs` integrates actual Express,
Fastify, HTTP propagation, and SQLite/manual spans; worker and scheduler code uses
the same SDK package. Run them through the repository workspace, not copied SDK code.
