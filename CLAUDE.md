# Likenovel Service API - 배포 가이드

## 1단계: 코드 배포

```bash
# 로컬에서 dev 브랜치에 푸시
git push origin dev

# GitHub에서 PR 생성
# dev → prod 로 PR 생성 후 머지
```

또는 prod에 직접 푸시가 가능한지 테스트해보고, 되면:
```bash
git checkout prod
git merge dev
git push origin prod
```

---

## 2단계: 서버 접속

```bash
# WEB 서버 접속 (Bastion)
ssh -i ~/pem/ln_kp.pem ln-admin@ec2-3-34-11-39.ap-northeast-2.compute.amazonaws.com

# WAS 서버로 이동
ssh -i /home/ln-admin/.ssh/ln_kp.pem ln-admin@10.0.100.110

# 백엔드 디렉토리로 이동
cd /home/ln-admin/likenovel/api
```

---

## 3단계: 환경변수 확인/수정

```bash
cat .env
vi .env  # 필요시
```

---

## 4단계: DB 마이그레이션 (03~37번)

```bash
mysql -h 10.0.100.78 -P 3306 -u ln-admin -p
```

```sql
source /home/ln-admin/likenovel/api/dist/init/03-create_tables_for_admin_api.sql;
source /home/ln-admin/likenovel/api/dist/init/04-create_tables_for_partner_api.sql;
source /home/ln-admin/likenovel/api/dist/init/05-migration_tb_user_profile_apply.sql;
source /home/ln-admin/likenovel/api/dist/init/06-create_nice_identity_session_table.sql;
source /home/ln-admin/likenovel/api/dist/init/07-create_user_notification_log_table.sql;
source /home/ln-admin/likenovel/api/dist/init/08-migration_tb_user_gift_transaction.sql;
source /home/ln-admin/likenovel/api/dist/init/09-create_product_hit_log_table.sql;
source /home/ln-admin/likenovel/api/dist/init/10-create_product_review_like_comment_tables.sql;
source /home/ln-admin/likenovel/api/dist/init/11-create_product_review_report_table.sql;
source /home/ln-admin/likenovel/api/dist/init/12-alter_user_block_for_review.sql;
source /home/ln-admin/likenovel/api/dist/init/13-alter_product_review_add_title.sql;
source /home/ln-admin/likenovel/api/dist/init/14-migration_chat_system.sql;
source /home/ln-admin/likenovel/api/dist/init/15-migration_chat_user_based.sql;
source /home/ln-admin/likenovel/api/dist/init/16-migration_chat_room_reports.sql;
source /home/ln-admin/likenovel/api/dist/init/17-alter_product_contract_offer_add_message.sql;
source /home/ln-admin/likenovel/api/dist/init/18-alter_user_productbook_add_acquisition_type.sql;
source /home/ln-admin/likenovel/api/dist/init/19-alter_user_report.sql;
source /home/ln-admin/likenovel/api/dist/init/20-alter_store_order.sql;
source /home/ln-admin/likenovel/api/dist/init/21-alter_user_productbook.sql;
source /home/ln-admin/likenovel/api/dist/init/22-create_product_review_comment_report_table.sql;
source /home/ln-admin/likenovel/api/dist/init/23-alter_user_giftbook_restructure.sql;
source /home/ln-admin/likenovel/api/dist/init/24-alter_user_profile_add_paid_change_count.sql;
source /home/ln-admin/likenovel/api/dist/init/25-alter_user_product_recent_add_unique_index.sql;
source /home/ln-admin/likenovel/api/dist/init/26-alter_product_contract_offer_author_accept_yn_default.sql;
source /home/ln-admin/likenovel/api/dist/init/27-alter_payment_statistics_by_user_unique_key.sql;
source /home/ln-admin/likenovel/api/dist/init/28-migration_algorithm_recommend_user_auto_populate.sql;
source /home/ln-admin/likenovel/api/dist/init/29-migration_update_withdrawn_user_emails.sql;
source /home/ln-admin/likenovel/api/dist/init/30-alter_direct_promotion_add_pending_and_end_status.sql;
source /home/ln-admin/likenovel/api/dist/init/31-alter_user_giftbook_expiration.sql;
source /home/ln-admin/likenovel/api/dist/init/32-alter_user_cashbook_transaction_add_sponsor_fields.sql;
source /home/ln-admin/likenovel/api/dist/init/33-alter_ptn_sponsorship_recodes_add_sponsor_type.sql;
source /home/ln-admin/likenovel/api/dist/init/34-alter_product_episode_add_open_changed_date.sql;
source /home/ln-admin/likenovel/api/dist/init/35-alter_sponsorship_add_author_id.sql;
source /home/ln-admin/likenovel/api/dist/init/36-alter_product_uci_column_size.sql;
source /home/ln-admin/likenovel/api/dist/init/37-add_ptn_statistics_indexes.sql;
```

---

## 5단계: 환경변수 수정 (필요시)

**중요: PM2는 `.env` 파일이 아닌 `ecosystem.config.js`에서 환경변수를 읽음**

```bash
# 환경변수 확인
cat ecosystem.config.js

# 환경변수 수정
vi ecosystem.config.js
```

환경변수 수정 후에는 반드시 `pm2 delete` 후 `pm2 start`로 재시작해야 함:
```bash
pm2 delete api && pm2 start ecosystem.config.js && pm2 save
```

**주의:** `pm2 restart --update-env`는 ecosystem.config.js의 새 환경변수를 로드하지 않음

---

## 6단계: 서비스 재시작 (필요시)

```bash
pm2 list
pm2 restart all
```

---

## 7단계: 확인

```bash
pm2 logs
curl http://localhost:3010/health
```
