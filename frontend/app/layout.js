import "./globals.css";

export const metadata = {
  title: "SeekJob",
  description: "SeekJob: upload CV, review AI analysis, and search matching LinkedIn public jobs.",
  icons: {
    icon: "/icon.png",
    shortcut: "/icon.png",
    apple: "/icon.png",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
