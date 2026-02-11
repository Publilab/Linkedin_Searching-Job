import "./globals.css";

export const metadata = {
  title: "SeekJob",
  description: "SeekJob: upload CV, review AI analysis, and search matching LinkedIn public jobs.",
  icons: {
    icon: "/icon.svg",
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
