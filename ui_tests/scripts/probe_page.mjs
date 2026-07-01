/**
 * Probe a URL: title, interactive elements, optional screenshot (base64).
 * Usage: node scripts/probe_page.mjs "https://example.com"
 */
import { chromium } from "playwright";

const url = process.argv[2];
if (!url) {
  console.log(JSON.stringify({ ok: false, error: "missing url" }));
  process.exit(1);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  ignoreHTTPSErrors: true,
});
const page = await context.newPage();

try {
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  } catch {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  }
  await page.waitForTimeout(1200);

  const info = await page.evaluate(() => {
    const pick = (el) => ({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || undefined,
      name: el.getAttribute("name") || undefined,
      id: el.id || undefined,
      placeholder: el.getAttribute("placeholder") || undefined,
      text: (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 48) || undefined,
      role: el.getAttribute("role") || undefined,
      testId: el.getAttribute("data-testid") || undefined,
      href: el.tagName === "A" ? el.getAttribute("href") || undefined : undefined,
      ariaLabel: el.getAttribute("aria-label") || undefined,
    });
    const seen = new Set();
    const elements = [];
    const selectors =
      'input, button, a[href], select, textarea, [role="button"], [role="link"], [role="textbox"], [contenteditable="true"]';
    for (const el of document.querySelectorAll(selectors)) {
      if (!(el instanceof HTMLElement)) continue;
      if (el.offsetParent === null && el.tagName !== "INPUT") continue;
      const key = `${el.tagName}|${el.id}|${el.getAttribute("name")}|${(el.innerText || "").slice(0, 20)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      elements.push(pick(el));
      if (elements.length >= 60) break;
    }
    const headings = [...document.querySelectorAll("h1,h2,h3")]
      .slice(0, 8)
      .map((h) => (h.innerText || "").trim().slice(0, 60))
      .filter(Boolean);
    return {
      title: document.title,
      final_url: location.href,
      headings,
      elements,
    };
  });

  const screenshot_base64 = (await page.screenshot({ type: "png", fullPage: false })).toString("base64");

  console.log(
    JSON.stringify({
      ok: true,
      url,
      ...info,
      element_count: info.elements.length,
      screenshot_base64,
    })
  );
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: String(e?.message || e), url }));
  process.exitCode = 1;
} finally {
  await browser.close();
}
