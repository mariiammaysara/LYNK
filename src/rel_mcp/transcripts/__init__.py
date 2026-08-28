"""Meeting transcript ingestion (P21) — engines that turn audio into text.

Every module in this package is a client: one network call, one pydantic
model back. No decision logic (where a transcript belongs, what to do with
it) lives here — that's a downstream module's job.
"""
