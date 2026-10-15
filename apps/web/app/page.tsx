import Hero from "../components/Hero";
import SiteNav from "../components/SiteNav";
import {
  ClosingCta,
  Customers,
  FaqSection,
  Loss,
  Overview,
  Problem,
  Proof,
  SiteFooter,
  Solution,
  WhyBetter,
} from "../components/Sections";

export default function Page() {
  return (
    <div className="page">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <SiteNav />
      <main id="main">
        <Hero />
        <Problem />
        <Loss />
        <Solution />
        <Customers />
        <WhyBetter />
        <Proof />
        <Overview />
        <FaqSection />
        <ClosingCta />
      </main>
      <SiteFooter />
    </div>
  );
}
