-- =====================================================================
-- マイグレーション 001  購入手続き中の選択を保持するテーブル
--
-- 【追加の理由】
--   設計仕様書 6.4.5 は、注文確定の要求本文を expectedTotal のみとし、
--   明細・配送先・支払方法はサーバー側から取得すると定めている。
--   しかし 3章のデータ設計に、配送方法や支払方法の選択を保持する場所が
--   定義されていなかった。実装の段階で判明した設計の欠落である。
--
--   cart に列を足す案もあるが、cart はログインをまたいで長く残る一方、
--   購入手続きの選択は一時的なものである。寿命が違うため分ける。
--
-- 実行:  python db/run_sql.py db/migrate_001_checkout.sql
-- 何度実行しても同じ結果になる（IF NOT EXISTS）。
-- =====================================================================

USE gu_ec_nakaoki;

CREATE TABLE IF NOT EXISTS checkout (
  cart_id                BIGINT        NOT NULL,
  delivery_method        VARCHAR(20)   NULL COMMENT 'HOME / STORE_PICKUP / NEKOPOSU',
  placement_type         VARCHAR(20)   NULL COMMENT '置き配の場所。利用しない場合は NULL',
  recipient_name         VARCHAR(100)  NULL,
  recipient_postal_code  VARCHAR(8)    NULL,
  recipient_address      VARCHAR(200)  NULL,
  recipient_phone        VARCHAR(20)   NULL,
  payment_method         VARCHAR(20)   NULL COMMENT 'CREDIT_CARD / PAYPAY / D_BARAI / DEFERRED / COD',
  updated_at             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                       ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (cart_id),
  CONSTRAINT fk_checkout_cart FOREIGN KEY (cart_id) REFERENCES cart (cart_id)
    ON DELETE CASCADE,
  -- 置き配は指定住所受取りでのみ意味を持つ
  CONSTRAINT chk_checkout_placement
    CHECK (placement_type IS NULL OR delivery_method = 'HOME')
) ENGINE=InnoDB COMMENT='購入手続き中の選択（実装時に追加）';
