import { loadSitemapIndex } from "../../src/features/seo/sitemap-sections";
import { sitemapIndexXml, xmlResponse } from "../../src/features/seo/sitemap-xml";

/**
 * Sitemap index (ADR-022, docs/seo/DECISIONS.md 12): one child per section with URLs. Content is
 * static per deploy, so it is built at build time. Non-production environments are kept out of
 * search engines by robots.txt and `X-Robots-Tag`, not by hiding the sitemap, so gating can be
 * tested against fixtures.
 */
export const dynamic = "force-static";
// Also regenerate every 10 minutes: a build-time admin read that fails (a cold admin) is caught and
// leaves no content tags on this entry, so publish events alone would never refresh it.
export const revalidate = 600;

export async function GET(): Promise<Response> {
  return xmlResponse(sitemapIndexXml(await loadSitemapIndex()));
}
