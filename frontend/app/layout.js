import "./globals.css";

export const metadata = {
  title: "CV LinkedIn Job Finder",
  description: "Upload CV, review summary, and search matching LinkedIn public jobs.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
