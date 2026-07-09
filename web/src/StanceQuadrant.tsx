// ---------------------------------------------------------------------------
// StanceQuadrant — 立场象限(⑧,人物志通用镜头之一),争议感知版
//
// 真·十字轴四象限,两条**可配**的连续轴(每本书由分析现场挑;三国 = 权势 × 立场)。
// 关键升级(接 exp024 probe，把争议判断做硬):立场不再是一个笃定的分 + 单句证据,而是
// Toulmin 那套——正据 + 反据 + 综合倾向(net)+ 争议度(dispute)。可视化跟着诚实:
//   · 争议小(dispute 低）→ 画一个笃定实点(诸葛亮尊汉、董卓篡逆);
//   · 争议大(dispute 高）→ **不画笃定点**:画一条竖向不确定带(高∝争议度)+ 空心点 + "争"标,
//     一眼看出"这人立场有争议、别当定论"(曹操尊汉vs篡逆千年争议)。
//   · 点开 → 正反两方证据分列(各自原文 + 核验),自己看、自己判,不塞给你一个结论。
//
// 通用:只认 {x, y=net, group, size, dispute, pro, con} + 轴配置,跟具体书 / 维度无关。
// 数据都 grounded:pro/con 都锚原文(核不过标待核),争议度经 probe 验过校得准、不 cherry-pick。
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { SealMark } from "./SealMark";

export interface QuadEvid {
  原文: string;
  说明: string;
  verified?: boolean;
}
export interface QuadPoint {
  name: string;
  x: number;
  y: number; // net 综合倾向
  group: string;
  size: number;
  dispute: number; // 0-5 争议度
  disputeReason?: string;
  pro: QuadEvid[];
  con: QuadEvid[];
}

interface AxisCfg {
  label: string;
  low: string;
  high: string;
}
interface Props {
  points: QuadPoint[];
  axisX: AxisCfg;
  axisY: AxisCfg;
  groupColor: Record<string, string>;
  defaultColor?: string;
  xMid?: number;
  yMid?: number;
  // 受控选中：传了就由父级管选中态（立场格局用它把象限点击 / 名册点击接到同一个人）；
  // 不传 = 组件自管、内置详情浮层照旧（老用法）。
  selected?: string | null;
  onSelect?: (name: string | null) => void;
  // 详情浮层：默认自带（selP 那块）；父级要自己渲染详情时（立场格局用 PersonDossier 的
  // 正反证据面板）传 false 关掉，免得两块详情重复。
  showDetail?: boolean;
}

const VB_W = 680;
const VB_H = 430;
const PAD = { t: 34, r: 74, b: 40, l: 60 };
const PW = VB_W - PAD.l - PAD.r;
const PH = VB_H - PAD.t - PAD.b;
const DISPUTE_HI = 3; // ≥ 此值算"有争议",不画笃定点

export function StanceQuadrant({
  points,
  axisX,
  axisY,
  groupColor,
  defaultColor = "#8a7f6a",
  xMid,
  yMid = 0,
  selected,
  onSelect,
  showDetail = true,
}: Props) {
  const [internalSel, setInternalSel] = useState<string | null>(null);
  const controlled = selected !== undefined;
  const sel: string | null = selected !== undefined ? selected : internalSel;
  const pick = (name: string) => {
    const next = sel === name ? null : name;
    if (!controlled) setInternalSel(next);
    onSelect?.(next);
  };

  const { xLo, xHi, yAbs } = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => Math.abs(p.y));
    return { xLo: Math.min(0, ...xs), xHi: Math.max(1, ...xs), yAbs: Math.max(1, ...ys, 5) };
  }, [points]);

  const sx = (x: number) => PAD.l + ((x - xLo) / (xHi - xLo || 1)) * PW;
  const sy = (y: number) => PAD.t + (1 - (y + yAbs) / (2 * yAbs || 1)) * PH;
  const color = (g: string) => groupColor[g] ?? defaultColor;

  // 防重叠:点按 x/y 落位后成对推开(争议度不同的人可能落在同一处)
  const laid = useMemo(() => {
    const rL = (m: number) => 5 + Math.min(12, Math.sqrt(Math.max(0, m)) * 1.6);
    const pts = points.map((p) => ({ p, cx: sx(p.x), cy: sy(p.y), r: rL(p.size) }));
    for (let it = 0; it < 70; it++) {
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const a = pts[i];
          const b = pts[j];
          const dx = b.cx - a.cx;
          const dy = b.cy - a.cy;
          const d = Math.hypot(dx, dy) || 0.01;
          const min = a.r + b.r + 12;
          if (d < min) {
            const k = (min - d) / 2 / d;
            a.cx -= dx * k;
            a.cy -= dy * k;
            b.cx += dx * k;
            b.cy += dy * k;
          }
        }
      }
      for (const q of pts) {
        q.cx = Math.max(PAD.l + q.r, Math.min(VB_W - PAD.r - q.r, q.cx));
        q.cy = Math.max(PAD.t + 30 + q.r, Math.min(VB_H - PAD.b - q.r, q.cy));
      }
    }
    return pts;
  }, [points, xLo, xHi, yAbs]); // eslint-disable-line react-hooks/exhaustive-deps

  const cxMid = sx(xMid ?? (xLo + xHi) / 2);
  const cyMid = sy(yMid);
  const groups = [...new Set(points.map((p) => p.group))];
  const selP = sel ? points.find((p) => p.name === sel) ?? null : null;

  return (
    <div className="rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-3">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full" style={{ overflow: "visible" }}>
        <rect x={cxMid} y={PAD.t} width={VB_W - PAD.r - cxMid} height={cyMid - PAD.t} fill="var(--color-seal)" opacity={0.03} />
        <rect x={PAD.l} y={cyMid} width={cxMid - PAD.l} height={VB_H - PAD.b - cyMid} fill="var(--color-ink)" opacity={0.03} />
        <line x1={cxMid} y1={PAD.t - 6} x2={cxMid} y2={VB_H - PAD.b + 6} stroke="var(--color-rule)" strokeWidth={1.5} />
        <line x1={PAD.l - 6} y1={cyMid} x2={VB_W - PAD.r + 6} y2={cyMid} stroke="var(--color-rule)" strokeWidth={1.5} />
        <text x={VB_W - PAD.r + 8} y={cyMid - 6} fontSize={12} fill="var(--color-ink-muted)">{axisX.high}</text>
        <text x={PAD.l - 8} y={cyMid - 6} fontSize={12} fill="var(--color-ink-muted)" textAnchor="end">{axisX.low}</text>
        <text x={cxMid + 6} y={PAD.t - 2} fontSize={12} fill="var(--color-ink-muted)">{axisY.high}</text>
        <text x={cxMid + 6} y={VB_H - PAD.b + 16} fontSize={12} fill="var(--color-ink-muted)">{axisY.low}</text>
        <text x={VB_W - PAD.r + 8} y={VB_H - PAD.b + 16} fontSize={11} fill="var(--color-ink-muted)" textAnchor="end" style={{ fontFamily: "var(--font-display)" }}>{axisX.label} →</text>

        {laid.map(({ p, cx, cy, r }) => {
          const on = sel === p.name;
          const c = color(p.group);
          const contested = p.dispute >= DISPUTE_HI;
          // 争议大:竖向不确定带(高 ∝ 争议度),范围内立场"说不准"
          const bandH = contested ? (p.dispute / 5) * 96 : 0;
          return (
            <g key={p.name} style={{ cursor: "pointer" }} onClick={() => pick(p.name)}>
              {contested && (
                <>
                  <rect x={cx - r} y={cy - bandH / 2} width={r * 2} height={bandH} rx={r} fill={c} opacity={0.14} />
                  <text x={cx + r + 2} y={cy - bandH / 2 + 4} fontSize={10.5} fill={c}>争{p.dispute}</text>
                </>
              )}
              <circle
                cx={cx}
                cy={cy}
                r={r}
                fill={contested ? "var(--color-paper-raised)" : c}
                opacity={on ? 1 : 0.88}
                stroke={on ? "var(--color-ink)" : contested ? c : "var(--color-paper-raised)"}
                strokeWidth={contested ? 2.4 : on ? 2 : 1.5}
                strokeDasharray={contested ? "3 2.5" : undefined}
              />
              <text x={cx} y={cy - (contested ? bandH / 2 : r) - 5} fontSize={11.5} textAnchor="middle" fill="var(--color-ink)" style={{ fontFamily: "var(--font-display)" }}>{p.name}</text>
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-[var(--color-ink-muted)]">
        {groups.map((g) => (
          <span key={g} className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full" style={{ background: color(g) }} />
            {g}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-4 rounded-sm border border-dashed border-[var(--color-ink-muted)]" />
          虚线空心 + 竖带＝立场有争议
        </span>
      </div>

      {showDetail && selP && (
        <div className="mt-2 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] px-3 py-2.5">
          <div className="flex items-center justify-between gap-2 mb-1">
            <p className="text-sm text-[var(--color-ink)]">
              <span className="font-bold" style={{ fontFamily: "var(--font-display)" }}>{selP.name}</span>
              <span className="text-[var(--color-ink-muted)]">
                {" · "}{selP.group} · 综合倾向 {selP.y > 1 ? `偏${axisY.high}` : selP.y < -1 ? `偏${axisY.low}` : "中立"}（{selP.y > 0 ? `+${selP.y}` : selP.y}）
                {selP.dispute >= DISPUTE_HI ? ` · 争议度 ${selP.dispute}（别当定论）` : ` · 争议度 ${selP.dispute}`}
              </span>
            </p>
          </div>
          {selP.disputeReason && (
            <p className="text-xs text-[var(--color-ink-muted)] mb-2 leading-relaxed">{selP.disputeReason}</p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <EvidCol title={`${axisY.high}的证据`} tint="var(--color-seal)" items={selP.pro} />
            <EvidCol title={`${axisY.low}的证据`} tint="var(--color-ink)" items={selP.con} />
          </div>
        </div>
      )}

      <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
        两轴每本书按分析换（当前：{axisX.label} × {axisY.label}）。立场走 Toulmin：正反证据都摆、锚原文；争议大的不画定论，自己看两方判。
      </p>
    </div>
  );
}

function EvidCol({ title, tint, items }: { title: string; tint: string; items: QuadEvid[] }) {
  return (
    <div>
      <div className="text-xs font-medium mb-1" style={{ color: tint }}>
        {title}（{items.length}）
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-[var(--color-ink-muted)]">原文里没找到这方证据。</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((e, i) => (
            <li key={i} className="text-sm text-[var(--color-ink)] leading-relaxed">
              <span className="inline-flex items-center gap-1 align-middle mr-1">
                {e.verified ? <SealMark size={16} title="原文已核验" /> : (
                  <span className="text-[10px] text-[var(--color-ink-muted)] px-1 rounded border border-[var(--color-rule)]">待核</span>
                )}
              </span>
              {e.原文}
              {e.说明 && <span className="text-xs text-[var(--color-ink-muted)]">（{e.说明}）</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
