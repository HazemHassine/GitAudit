import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "OSS Maintainer — Command Center",
  description: "Evidence-first repository reliability console",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
