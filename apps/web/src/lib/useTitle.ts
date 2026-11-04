import { useEffect } from "react";

/** Tiêu đề tab trình duyệt: "<trang> · EventRank". */
export function useTitle(title: string | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · EventRank` : "EventRank — Sự kiện tin tức Việt Nam";
  }, [title]);
}
