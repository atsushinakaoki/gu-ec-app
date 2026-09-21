export const yen = (n: number) => `¥${n.toLocaleString("ja-JP")}`;

/** mm を GU の表記に合わせて cm（小数1桁）で出す。例: 705 → "70.5cm" */
export const cm = (mm: number) => `${(mm / 10).toFixed(1)}cm`;

export const GENDER_NAMES: Record<string, string> = { WOMEN: "WOMEN", MEN: "MEN", KIDS: "KIDS" };

export const ALTERATION_NAMES: Record<string, string> = {
  SINGLE_FOLD: "シングル",
  DOUBLE_FOLD: "ダブル",
};

// 商品画像の代わりに使う色見本。カラーコードは seed.sql に対応する
const SWATCHES: Record<string, string> = {
  "00": "#f2f1ee",
  "09": "#1f1f1f",
  "30": "#d9822b",
  "32": "#d6c6a5",
  "57": "#55694f",
  "65": "#3d5c8f",
};
export const swatch = (colorCode: string) => SWATCHES[colorCode] ?? "#9a9a9a";

/** 残り時間を「あと◯分」で返す。過ぎていれば null */
export function minutesLeft(isoUtc: string | null, now: number): number | null {
  if (!isoUtc) return null;
  const ms = new Date(isoUtc).getTime() - now;
  return ms > 0 ? Math.ceil(ms / 60000) : null;
}

/** 表示用。Backend はハイフンを除いて保持している（fingerprint の揺れを防ぐため） */
export const postal = (digits: string) =>
  /^\d{7}$/.test(digits) ? `${digits.slice(0, 3)}-${digits.slice(3)}` : digits;
