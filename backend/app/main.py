from fastapi import FastAPI

app = FastAPI(title="Pricing Engine")


@app.get("/health")
def health() -> dict[str, str]:
    """Report service liveness for deployment healthchecks.

    Returns:
        A minimal status payload.
    """
    return {"status": "ok"}
