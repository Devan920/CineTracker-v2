import { useEffect } from "react";

interface DocumentMetaOptions {
  title: string;
  description: string;
  image?: string | null;
  url?: string;
}

function setMetaContent(attr: "name" | "property", key: string, value: string): void {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", value);
}

export function useDocumentMeta({ title, description, image, url }: DocumentMetaOptions): void {
  useEffect(() => {
    document.title = title;
    const targetUrl = url || window.location.href;
    const targetImg = (image && image.trim()) || `${window.location.origin}/icons/icon-512.svg`;

    setMetaContent("name", "description", description);
    setMetaContent("property", "og:title", title);
    setMetaContent("property", "og:description", description);
    setMetaContent("property", "og:image", targetImg);
    setMetaContent("property", "og:url", targetUrl);
    setMetaContent("name", "twitter:title", title);
    setMetaContent("name", "twitter:description", description);
    setMetaContent("name", "twitter:image", targetImg);
  }, [title, description, image, url]);
}
