-- =====================================================================
-- GUオンラインストア  スキーマ定義
--   設計仕様書 3. データ設計 に対応
--   対象: MySQL 8.0
-- =====================================================================
--
-- 【注意】
--   order は MySQL の予約語のため、テーブル名を orders としている。
--   設計仕様書 3.3.9 の order テーブルに対応する。
-- =====================================================================

CREATE DATABASE IF NOT EXISTS gu_ec_nakaoki
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE gu_ec_nakaoki;

-- 依存関係の逆順に削除（再実行を可能とするため）
DROP TABLE IF EXISTS checkout;
DROP TABLE IF EXISTS reservation;
DROP TABLE IF EXISTS order_item;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS cart_item;
DROP TABLE IF EXISTS cart;
DROP TABLE IF EXISTS stock;
DROP TABLE IF EXISTS sku;
DROP TABLE IF EXISTS product;
DROP TABLE IF EXISTS location;
DROP TABLE IF EXISTS member;


-- ---------------------------------------------------------------------
-- 1. product（商品）  設計仕様書 3.3.1
--    価格は品番単位で保持する（FR-531-14）
-- ---------------------------------------------------------------------
CREATE TABLE product (
  product_id                VARCHAR(20)   NOT NULL COMMENT '商品番号',
  name                      VARCHAR(200)  NOT NULL COMMENT '商品名',
  gender                    VARCHAR(10)   NOT NULL COMMENT 'WOMEN / MEN / KIDS',
  regular_price             INT           NOT NULL COMMENT '通常売価（税抜）',
  member_price              INT           NULL     COMMENT '会員価格（税抜）',
  member_price_from         DATETIME      NULL     COMMENT '会員価格の適用開始',
  member_price_to           DATETIME      NULL     COMMENT '会員価格の適用終了',
  alterable                 BOOLEAN       NOT NULL DEFAULT FALSE COMMENT 'すそ上げ加工の可否',
  original_length_mm        INT           NULL     COMMENT '元の丈（mm）',
  min_alteration_length_mm  INT           NULL     COMMENT '加工可能な最短の丈（mm）DS-311',
  created_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (product_id),
  -- DS-312: alterable = true の商品は min <= original であること
  CONSTRAINT chk_product_alteration_range
    CHECK (
      alterable = FALSE
      OR (original_length_mm IS NOT NULL
          AND min_alteration_length_mm IS NOT NULL
          AND min_alteration_length_mm <= original_length_mm)
    ),
  CONSTRAINT chk_product_price_non_negative
    CHECK (regular_price >= 0 AND (member_price IS NULL OR member_price >= 0))
) ENGINE=InnoDB COMMENT='商品（品番単位）';


-- ---------------------------------------------------------------------
-- 2. sku（SKU）  設計仕様書 3.3.2
-- ---------------------------------------------------------------------
CREATE TABLE sku (
  sku_id      VARCHAR(30)  NOT NULL COMMENT 'SKU識別子',
  product_id  VARCHAR(20)  NOT NULL,
  color_code  VARCHAR(10)  NOT NULL COMMENT 'カラーコード（例: 09）',
  color_name  VARCHAR(50)  NOT NULL COMMENT 'カラー名（例: BLACK）',
  size        VARCHAR(10)  NOT NULL COMMENT 'XS / S / M / L / XL / XXL / 3XL / ONE',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (sku_id),
  UNIQUE KEY uq_sku_combination (product_id, color_code, size),
  CONSTRAINT fk_sku_product FOREIGN KEY (product_id) REFERENCES product (product_id)
) ENGINE=InnoDB COMMENT='SKU（品番 × カラー × サイズ）';


-- ---------------------------------------------------------------------
-- 3. location（在庫ロケーション）  設計仕様書 3.3.3
--    (1)ではオンラインのみ使用。(2)-a 以降で店舗を追加する
-- ---------------------------------------------------------------------
CREATE TABLE location (
  location_id  INT           NOT NULL AUTO_INCREMENT,
  type         VARCHAR(10)   NOT NULL COMMENT 'ONLINE / STORE',
  name         VARCHAR(100)  NOT NULL COMMENT '表示名',
  address      VARCHAR(200)  NULL     COMMENT 'STORE のみ',
  latitude     DECIMAL(9,6)  NULL     COMMENT 'STORE のみ',
  longitude    DECIMAL(9,6)  NULL     COMMENT 'STORE のみ',
  is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
  PRIMARY KEY (location_id)
) ENGINE=InnoDB COMMENT='在庫ロケーション';


-- ---------------------------------------------------------------------
-- 4. stock（在庫）  設計仕様書 3.3.4
--    引当済み数を列として持たない。reservation から算出する
-- ---------------------------------------------------------------------
CREATE TABLE stock (
  sku_id       VARCHAR(30)  NOT NULL,
  location_id  INT          NOT NULL,
  quantity     INT          NOT NULL COMMENT '実在庫数',
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (sku_id, location_id),
  CONSTRAINT fk_stock_sku      FOREIGN KEY (sku_id)      REFERENCES sku (sku_id),
  CONSTRAINT fk_stock_location FOREIGN KEY (location_id) REFERENCES location (location_id),
  -- DS-321: 負の在庫数を保持しない
  CONSTRAINT chk_stock_quantity_non_negative CHECK (quantity >= 0)
) ENGINE=InnoDB COMMENT='在庫（SKU × ロケーション）';


-- ---------------------------------------------------------------------
-- 5. member（会員）  設計仕様書 3.3.6
--    退会時に行を削除しない（論理削除）
-- ---------------------------------------------------------------------
CREATE TABLE member (
  member_id      BIGINT        NOT NULL AUTO_INCREMENT,
  email          VARCHAR(255)  NOT NULL COMMENT 'ログインID',
  password_hash  VARCHAR(255)  NOT NULL COMMENT 'ハッシュ値。平文は保持しない',
  name           VARCHAR(100)  NOT NULL,
  postal_code    VARCHAR(8)    NULL,
  address        VARCHAR(200)  NULL,
  phone          VARCHAR(20)   NULL,
  is_withdrawn   BOOLEAN       NOT NULL DEFAULT FALSE COMMENT '退会フラグ',
  withdrawn_at   DATETIME      NULL,
  created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (member_id),
  UNIQUE KEY uq_member_email (email)
) ENGINE=InnoDB COMMENT='会員';


-- ---------------------------------------------------------------------
-- 6. cart（カート）  設計仕様書 3.3.7
--    member_id と session_id のいずれか一方が必ず設定される
-- ---------------------------------------------------------------------
CREATE TABLE cart (
  cart_id     BIGINT       NOT NULL AUTO_INCREMENT,
  member_id   BIGINT       NULL     COMMENT '未ログイン時は NULL',
  session_id  VARCHAR(64)  NULL     COMMENT '未ログイン時の識別子',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                           ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (cart_id),
  UNIQUE KEY uq_cart_member  (member_id),
  UNIQUE KEY uq_cart_session (session_id),
  CONSTRAINT fk_cart_member FOREIGN KEY (member_id) REFERENCES member (member_id),
  CONSTRAINT chk_cart_owner
    CHECK (member_id IS NOT NULL OR session_id IS NOT NULL)
) ENGINE=InnoDB COMMENT='カート';


-- ---------------------------------------------------------------------
-- 7. cart_item（カート明細）  設計仕様書 3.3.8
--    明細の同一性は sku_id + alteration_type + alteration_length_mm（DS-428）
-- ---------------------------------------------------------------------
CREATE TABLE cart_item (
  cart_item_id          BIGINT       NOT NULL AUTO_INCREMENT,
  cart_id               BIGINT       NOT NULL,
  sku_id                VARCHAR(30)  NOT NULL,
  quantity              INT          NOT NULL,
  alteration_type       VARCHAR(30)  NULL COMMENT '加工方法。指定しない場合は NULL',
  alteration_length_mm  INT          NULL COMMENT '仕上がり丈（mm）。5mm刻み',
  created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (cart_item_id),
  KEY idx_cart_item_cart (cart_id),
  CONSTRAINT fk_cart_item_cart FOREIGN KEY (cart_id) REFERENCES cart (cart_id)
    ON DELETE CASCADE,
  CONSTRAINT fk_cart_item_sku  FOREIGN KEY (sku_id)  REFERENCES sku (sku_id),
  -- 7.1.1: 数量は 1 以上 10 以下
  CONSTRAINT chk_cart_item_quantity CHECK (quantity BETWEEN 1 AND 10),
  -- FR-564-02: 加工方法と丈は、双方が設定されるか双方が NULL であること
  CONSTRAINT chk_cart_item_alteration
    CHECK (
      (alteration_type IS NULL     AND alteration_length_mm IS NULL)
      OR
      (alteration_type IS NOT NULL AND alteration_length_mm IS NOT NULL)
    )
) ENGINE=InnoDB COMMENT='カート明細';


-- ---------------------------------------------------------------------
-- 8. orders（注文）  設計仕様書 3.3.9
-- ---------------------------------------------------------------------
CREATE TABLE orders (
  order_id                BIGINT        NOT NULL AUTO_INCREMENT,
  order_number            VARCHAR(20)   NOT NULL COMMENT '顧客に提示する注文番号',
  member_id               BIGINT        NOT NULL,
  status                  VARCHAR(20)   NOT NULL COMMENT 'PENDING_PAYMENT / CONFIRMED / FAILED',
  delivery_method         VARCHAR(20)   NOT NULL COMMENT 'HOME / STORE_PICKUP / NEKOPOSU',
  placement_type          VARCHAR(20)   NULL     COMMENT '置き配指定。HOME のときのみ',
  payment_method          VARCHAR(20)   NOT NULL COMMENT 'CREDIT_CARD / PAYPAY / D_BARAI / DEFERRED / COD',
  payment_transaction_id  VARCHAR(100)  NULL     COMMENT 'PSP が発行する取引ID',
  idempotency_key         VARCHAR(64)   NOT NULL COMMENT '冪等キー（DS-459）',
  content_fingerprint     VARCHAR(64)   NOT NULL COMMENT '注文内容のハッシュ値（DS-460）',
  recipient_name          VARCHAR(100)  NOT NULL COMMENT '注文時点の値をコピー',
  recipient_postal_code   VARCHAR(8)    NOT NULL,
  recipient_address       VARCHAR(200)  NOT NULL,
  recipient_phone         VARCHAR(20)   NOT NULL,
  subtotal                INT           NOT NULL COMMENT '商品合計（税抜）',
  alteration_fee          INT           NOT NULL DEFAULT 0 COMMENT 'すそ上げ加工料の合計',
  shipping_fee            INT           NOT NULL DEFAULT 0 COMMENT '送料',
  payment_fee             INT           NOT NULL DEFAULT 0 COMMENT '支払手数料',
  tax                     INT           NOT NULL COMMENT '消費税',
  total                   INT           NOT NULL COMMENT '総額',
  ordered_at              DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id),
  UNIQUE KEY uq_orders_number          (order_number),
  -- DS-459: 同時到達を DB の制約により排除する
  UNIQUE KEY uq_orders_idempotency_key (idempotency_key),
  KEY idx_orders_member (member_id),
  CONSTRAINT fk_orders_member FOREIGN KEY (member_id) REFERENCES member (member_id),
  CONSTRAINT chk_orders_amounts_non_negative
    CHECK (subtotal >= 0 AND alteration_fee >= 0 AND shipping_fee >= 0
           AND payment_fee >= 0 AND tax >= 0 AND total >= 0)
) ENGINE=InnoDB COMMENT='注文';


-- ---------------------------------------------------------------------
-- 9. order_item（注文明細）  設計仕様書 3.3.10
--    product を参照せず、注文時点の値をコピーして保持する
-- ---------------------------------------------------------------------
CREATE TABLE order_item (
  order_item_id         BIGINT        NOT NULL AUTO_INCREMENT,
  order_id              BIGINT        NOT NULL,
  sku_id                VARCHAR(30)   NOT NULL,
  product_name          VARCHAR(200)  NOT NULL COMMENT '注文時点の商品名をコピー',
  color_name            VARCHAR(50)   NOT NULL COMMENT '注文時点のカラー名をコピー',
  size                  VARCHAR(10)   NOT NULL COMMENT '注文時点のサイズをコピー',
  unit_price            INT           NOT NULL COMMENT '注文時点の適用価格（税抜）',
  price_type            VARCHAR(20)   NOT NULL COMMENT 'REGULAR / MEMBER',
  quantity              INT           NOT NULL,
  alteration_type       VARCHAR(30)   NULL COMMENT '注文時点の加工方法をコピー',
  alteration_length_mm  INT           NULL,
  alteration_fee        INT           NULL COMMENT '注文時点の加工料をコピー',
  is_returnable         BOOLEAN       NOT NULL COMMENT '返品可否。加工品は false',
  PRIMARY KEY (order_item_id),
  KEY idx_order_item_order (order_id),
  CONSTRAINT fk_order_item_order FOREIGN KEY (order_id) REFERENCES orders (order_id),
  CONSTRAINT fk_order_item_sku   FOREIGN KEY (sku_id)   REFERENCES sku (sku_id),
  CONSTRAINT chk_order_item_quantity CHECK (quantity >= 1)
) ENGINE=InnoDB COMMENT='注文明細';


-- ---------------------------------------------------------------------
-- 10. reservation（在庫引当）  設計仕様書 3.3.5
--     引当可能数 = stock.quantity - SUM(ACTIVE かつ expires_at > now)
--     ※ CONFIRMED は減算しない（DS-341）
-- ---------------------------------------------------------------------
CREATE TABLE reservation (
  reservation_id  BIGINT       NOT NULL AUTO_INCREMENT,
  sku_id          VARCHAR(30)  NOT NULL,
  location_id     INT          NOT NULL,
  cart_item_id    BIGINT       NULL COMMENT 'カート起因の引当',
  order_id        BIGINT       NULL COMMENT '注文確定後の引当',
  quantity        INT          NOT NULL,
  status          VARCHAR(20)  NOT NULL COMMENT 'ACTIVE / CONFIRMED / RELEASED',
  expires_at      DATETIME     NULL COMMENT 'ACTIVE のときのみ。投入時刻 + 60分',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (reservation_id),
  -- 引当可能数の算出で使用する索引
  KEY idx_reservation_lookup    (sku_id, location_id, status, expires_at),
  KEY idx_reservation_cart_item (cart_item_id),
  KEY idx_reservation_order     (order_id),
  CONSTRAINT fk_reservation_sku       FOREIGN KEY (sku_id)      REFERENCES sku (sku_id),
  CONSTRAINT fk_reservation_location  FOREIGN KEY (location_id) REFERENCES location (location_id),
  CONSTRAINT fk_reservation_cart_item FOREIGN KEY (cart_item_id)
    REFERENCES cart_item (cart_item_id) ON DELETE SET NULL,
  CONSTRAINT fk_reservation_order FOREIGN KEY (order_id) REFERENCES orders (order_id),
  CONSTRAINT chk_reservation_quantity CHECK (quantity >= 1),
  -- ACTIVE のときは expires_at が必須
  CONSTRAINT chk_reservation_expires
    CHECK (status <> 'ACTIVE' OR expires_at IS NOT NULL)
) ENGINE=InnoDB COMMENT='在庫引当';


-- ---------------------------------------------------------------------
-- 11. checkout（購入手続き中の選択）  設計仕様書に定義なし。実装時に追加
--     経緯は migrate_001_checkout.sql を参照
-- ---------------------------------------------------------------------
CREATE TABLE checkout (
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
