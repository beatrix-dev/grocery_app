module.exports = function handler(_req, res) {
  const apiBaseUrl = process.env.GROCERY_API_BASE_URL;

  if (!apiBaseUrl) {
    res.status(500).json({
      error: "Set GROCERY_API_BASE_URL in your Vercel project settings.",
    });
    return;
  }

  res.status(200).json({ apiBaseUrl });
};
