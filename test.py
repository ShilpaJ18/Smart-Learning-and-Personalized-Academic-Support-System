def get_model():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("❌ GEMINI_API_KEY not found")

    genai.configure(api_key=key)

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        return model
    except Exception as e:
        raise RuntimeError(f"Model init failed: {e}")