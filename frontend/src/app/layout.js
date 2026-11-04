import "./globals.css";

export const metadata = {
  title: "LinkedIn Mailer — Post Scraper & Auto-Email",
  description: "Scrape LinkedIn posts, extract emails and job details, and send automated emails to recruiters.",
  keywords: "LinkedIn, scraper, email, automation, job search",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
