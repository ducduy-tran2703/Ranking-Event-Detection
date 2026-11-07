import { useState } from "react";
import type { Granularity } from "../api/client";
import { useHourOfDay, useTimeline } from "../api/queries";
import { Card } from "../components/Card";
import { GroupedBars, Lines } from "../components/charts";
import { FilterBar, useUrlFilter } from "../components/FilterBar";
import { ErrorBox } from "../components/Status";
import { pivot } from "../lib/pivot";

export function TimePage() {
  const { filter } = useUrlFilter();
  const stats = { source: filter.source, date_from: filter.date_from, date_to: filter.date_to };
  const [granularity, setGranularity] = useState<Granularity>("day");
  const timeline = useTimeline(stats, granularity);
  const hours = useHourOfDay(stats);

  const line = pivot(timeline.data ?? [], "bucket");
  const hourRows = (hours.data ?? []).map((r) => ({ ...r, hour: `${r.hour}h` }));
  const hourPivot = pivot(hourRows, "hour", Array.from({ length: 24 }, (_, h) => `${h}h`));

  return (
    <>
      <h1>Theo thời gian</h1>
      <FilterBar />
      <Card
        title="Số bài theo thời gian"
        hint={granularity === "hour" ? "Theo giờ — nên lọc khoảng ngày ngắn để dễ đọc." : "Theo ngày, giờ Việt Nam."}
        actions={
          <div className="seg">
            <button className={granularity === "day" ? "active" : ""} onClick={() => setGranularity("day")}>Ngày</button>
            <button className={granularity === "hour" ? "active" : ""} onClick={() => setGranularity("hour")}>Giờ</button>
          </div>
        }
      >
        {timeline.error ? <ErrorBox error={timeline.error} /> : <Lines data={line.data} xKey="bucket" sources={line.sources} />}
      </Card>
      <Card title="Phân bố theo giờ trong ngày" hint="Mỗi báo có nhịp đăng bài riêng — hữu ích khi đặt lịch chạy crawler.">
        {hours.error ? <ErrorBox error={hours.error} /> : <GroupedBars data={hourPivot.data} xKey="hour" sources={hourPivot.sources} />}
      </Card>
    </>
  );
}
