import "./globals.css";

export const metadata = {
  title: "POS Invoice Generator",
  description:
    "A simple Point-of-Sale system to create and download PDF invoices",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
