# Your SOPs go here

Put your own SOP Markdown files in this directory. Everything here except this
README is gitignored, so **client documents can never be committed by accident**.

Coming from PDFs? Convert them first:

```bash
python3 -m sop_pipeline.ingest --pdf-dir /path/to/pdfs --out data/sops
python3 -m sop_pipeline.cli run
```

With this directory empty, the pipeline falls back to the bundled demo corpus in
`examples/mock_corpus/` so a fresh clone runs immediately. As soon as you add a
`.md` file here, your corpus takes over.

Before your first real run, edit `config/site_config.json` — the regulatory
version table and expected coverage bands are site-specific.
