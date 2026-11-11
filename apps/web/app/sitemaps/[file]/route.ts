import { notFound } from "next/navigation";
import { loadSitemapSections } from "../../../src/features/seo/sitemap-sections";
import {
  isSitemapSection,
  sitemapSections,
  urlsetXml,
  xmlResponse,
} from "../../../src/features/seo/sitemap-xml";

/**
 * One child sitemap per section (`/sitemaps/pages.xml`, `insights.xml`, `careers.xml`): gate-open,
 * existing, canonical URLs only, with `lastmod` from content dates, never the build time.
 */
export const dynamic = "force-static";
// Also regenerate every 10 minutes: a build-time admin read that fails (a cold admin) is caught and
// leaves no content tags on this entry, so publish events alone would never refresh it.
export const revalidate = 600;
export const dynamicParams = false;

export function generateStaticParams(): { file: string }[] {
  return sitemapSections.map((section) => ({ file: `${section}.xml` }));
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ file: string }> },
): Promise<Response> {
  const section = (await params).file.replace(/\.xml$/, "");
  if (!isSitemapSection(section)) notFound();
  return xmlResponse(urlsetXml((await loadSitemapSections())[section]));
}
