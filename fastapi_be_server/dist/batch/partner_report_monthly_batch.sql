
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'partner_report_monthly_batch.sh'
;

start transaction;

-- 작품별 월매출
insert into tb_ptn_product_sales (product_id, title, author_nickname, contract_type, cp_company_name, paid_open_date, isbn, uci, series_regular_price, sale_price, sum_normal_price_web, sum_normal_price_playstore, sum_normal_price_ios, sum_normal_price_onestore, sum_ticket_price_web, sum_ticket_price_playstore, sum_ticket_price_ios, sum_ticket_price_onestore, sum_comped_ticket_price, fee_web, fee_playstore, fee_ios, fee_onestore, fee_comped_ticket, sum_refund_price_web, sum_refund_price_playstore, sum_refund_price_ios, sum_refund_price_onestore, sum_refund_comped_ticket_price, settlement_rate_web, settlement_rate_playstore, settlement_rate_ios, settlement_rate_onestore, settlement_rate_comped_ticket, sum_settlement_price_web, sum_settlement_comped_ticket_price, tax_price, total_price, created_id, updated_id)
select m.*
  from (
    with tmp_product_sales_summary as (
        -- 한달치
        select product_id
             , sum(sum_normal_price_web + sum_discount_price_web) as sum_normal_price_web
             , sum(sum_normal_price_playstore + sum_discount_price_playstore) as sum_normal_price_playstore
             , sum(sum_normal_price_ios + sum_discount_price_ios) as sum_normal_price_ios
             , sum(sum_normal_price_onestore + sum_discount_price_onestore) as sum_normal_price_onestore
             , sum(sum_paid_ticket_price_web + sum_free_ticket_price_web) as sum_ticket_price_web
             , sum(sum_paid_ticket_price_playstore + sum_free_ticket_price_playstore) as sum_ticket_price_playstore
             , sum(sum_paid_ticket_price_ios + sum_free_ticket_price_ios) as sum_ticket_price_ios
             , sum(sum_paid_ticket_price_onestore + sum_free_ticket_price_onestore) as sum_ticket_price_onestore
             , sum(sum_comped_ticket_price_web + sum_comped_ticket_price_playstore + sum_comped_ticket_price_ios + sum_comped_ticket_price_onestore) as sum_comped_ticket_price
             , sum(sum_refund_normal_price_web + sum_refund_discount_price_web + sum_refund_paid_ticket_price_web + sum_refund_free_ticket_price_web) as sum_refund_price_web
             , sum(sum_refund_normal_price_playstore + sum_refund_discount_price_playstore + sum_refund_paid_ticket_price_playstore + sum_refund_free_ticket_price_playstore) as sum_refund_price_playstore
             , sum(sum_refund_normal_price_ios + sum_refund_discount_price_ios + sum_refund_paid_ticket_price_ios + sum_refund_free_ticket_price_ios) as sum_refund_price_ios
             , sum(sum_refund_normal_price_onestore + sum_refund_discount_price_onestore + sum_refund_paid_ticket_price_onestore + sum_refund_free_ticket_price_onestore) as sum_refund_price_onestore
             , sum(sum_refund_comped_ticket_price_web + sum_refund_comped_ticket_price_playstore + sum_refund_comped_ticket_price_ios + sum_refund_comped_ticket_price_onestore) as sum_refund_comped_ticket_price
          from tb_ptn_product_sales_temp_summary
         where created_date >= date_sub(curdate(), interval 1 month) - interval day(curdate()) - 1 day
           and created_date < curdate()
         group by product_id
    ),
    tmp_product_sales_list_summary as (
        select product_id
             , sum(case when item_type = 'normal' and device_type = 'web' then fee else 0 end) as fee_web
             , sum(case when item_type = 'normal' and device_type = 'playstore' then fee else 0 end) as fee_playstore
             , sum(case when item_type = 'normal' and device_type = 'ios' then fee else 0 end) as fee_ios
             , sum(case when item_type = 'normal' and device_type = 'onestore' then fee else 0 end) as fee_onestore
             , sum(case when item_type = 'comped' and device_type = 'web' then fee else 0 end) as fee_comped_ticket
             , sum(case when item_type = 'normal' and device_type = 'web' then settlement_rate else 0 end) as settlement_rate_web
             , sum(case when item_type = 'normal' and device_type = 'playstore' then settlement_rate else 0 end) as settlement_rate_playstore
             , sum(case when item_type = 'normal' and device_type = 'ios' then settlement_rate else 0 end) as settlement_rate_ios
             , sum(case when item_type = 'normal' and device_type = 'onestore' then settlement_rate else 0 end) as settlement_rate_onestore
             , sum(case when item_type = 'comped' and device_type = 'web' then settlement_rate else 0 end) as settlement_rate_comped_ticket
          from tb_cms_product_settlement
         where item_type in ('normal', 'comped')
         group by product_id
    )
    select a.product_id
         , a.title
         , a.author_nickname
         , a.contract_type
         , a.cp_company_name
         , a.paid_open_date
         , a.isbn
         , a.uci
         , a.series_regular_price
         , a.sale_price
         , b.sum_normal_price_web
         , b.sum_normal_price_playstore
         , b.sum_normal_price_ios
         , b.sum_normal_price_onestore
         , b.sum_ticket_price_web
         , b.sum_ticket_price_playstore
         , b.sum_ticket_price_ios
         , b.sum_ticket_price_onestore
         , b.sum_comped_ticket_price
         , round((b.sum_normal_price_web + b.sum_ticket_price_web - b.sum_refund_price_web) * (c.fee_web / 100), 0) as fee_web
         , round((b.sum_normal_price_playstore + b.sum_ticket_price_playstore - b.sum_refund_price_playstore) * (c.fee_playstore / 100), 0) as fee_playstore
         , round((b.sum_normal_price_ios + b.sum_ticket_price_ios - b.sum_refund_price_ios) * (c.fee_ios / 100), 0) as fee_ios
         , round((b.sum_normal_price_onestore + b.sum_ticket_price_onestore - b.sum_refund_price_onestore) * (c.fee_onestore / 100), 0) as fee_onestore
         , round((b.sum_comped_ticket_price - b.sum_refund_comped_ticket_price) * (c.fee_comped_ticket / 100), 0) as fee_comped_ticket
         , b.sum_refund_price_web
         , b.sum_refund_price_playstore
         , b.sum_refund_price_ios
         , b.sum_refund_price_onestore
         , b.sum_refund_comped_ticket_price
         , c.settlement_rate_web
         , c.settlement_rate_playstore
         , c.settlement_rate_ios
         , c.settlement_rate_onestore
         , c.settlement_rate_comped_ticket
         , round((b.sum_normal_price_web + b.sum_ticket_price_web - b.sum_refund_price_web) * ((100 - c.fee_web) / 100) * (c.settlement_rate_web / 100), 0) as sum_settlement_price_web
         , round((b.sum_comped_ticket_price - b.sum_refund_comped_ticket_price) * ((100 - c.fee_comped_ticket) / 100) * (c.settlement_rate_comped_ticket / 100), 0) as sum_settlement_comped_ticket_price
         , 0 as tax_price
         , (
             round((b.sum_normal_price_web + b.sum_ticket_price_web - b.sum_refund_price_web) * ((100 - c.fee_web) / 100) * (c.settlement_rate_web / 100), 0)
             + round((b.sum_comped_ticket_price - b.sum_refund_comped_ticket_price) * ((100 - c.fee_comped_ticket) / 100) * (c.settlement_rate_comped_ticket / 100), 0)
           ) as total_price
         , 0 as created_id
         , 0 as updated_id
      from tb_batch_daily_product_info_summary a
     inner join tmp_product_sales_summary b on a.product_id = b.product_id
     inner join tmp_product_sales_list_summary c on a.product_id = c.product_id
    ) m
 where m.product_id is not null
;

-- 월별 정산
insert into tb_ptn_product_settlement (product_id, item_type, device_type, sum_total_sales_price, fee, net_sales_price, taxable_price, vat_price, settlement_price, platform_revenue, privious_offer_amount, current_offer_amount, final_settlement_price, created_id, updated_id)
select m.*
  from (
    with tmp_product_settlement_summary as (
        -- 한달치
        select product_id
             , sum(sum_normal_price_web) as sum_normal_price_web
             , sum(sum_normal_price_playstore) as sum_normal_price_playstore
             , sum(sum_normal_price_ios) as sum_normal_price_ios
             , sum(sum_normal_price_onestore) as sum_normal_price_onestore
             , sum(sum_discount_price_web) as sum_discount_price_web
             , sum(sum_discount_price_playstore) as sum_discount_price_playstore
             , sum(sum_discount_price_ios) as sum_discount_price_ios
             , sum(sum_discount_price_onestore) as sum_discount_price_onestore
             , sum(sum_comped_ticket_price_web) as sum_comped_ticket_price_web
             , sum(sum_comped_ticket_price_playstore) as sum_comped_ticket_price_playstore
             , sum(sum_comped_ticket_price_ios) as sum_comped_ticket_price_ios
             , sum(sum_comped_ticket_price_onestore) as sum_comped_ticket_price_onestore
             , sum(sum_refund_normal_price_web) as sum_refund_normal_price_web
             , sum(sum_refund_normal_price_playstore) as sum_refund_normal_price_playstore
             , sum(sum_refund_normal_price_ios) as sum_refund_normal_price_ios
             , sum(sum_refund_normal_price_onestore) as sum_refund_normal_price_onestore
             , sum(sum_refund_discount_price_web) as sum_refund_discount_price_web
             , sum(sum_refund_discount_price_playstore) as sum_refund_discount_price_playstore
             , sum(sum_refund_discount_price_ios) as sum_refund_discount_price_ios
             , sum(sum_refund_discount_price_onestore) as sum_refund_discount_price_onestore
             , sum(sum_refund_comped_ticket_price_web) as sum_refund_comped_ticket_price_web
             , sum(sum_refund_comped_ticket_price_playstore) as sum_refund_comped_ticket_price_playstore
             , sum(sum_refund_comped_ticket_price_ios) as sum_refund_comped_ticket_price_ios
             , sum(sum_refund_comped_ticket_price_onestore) as sum_refund_comped_ticket_price_onestore
          from tb_ptn_product_sales_temp_summary
         where created_date >= date_sub(curdate(), interval 1 month) - interval day(curdate()) - 1 day
           and created_date < curdate()
         group by product_id
    ),
    tmp_product_settlement_list_summary as (
        select product_id
             , item_type
             , device_type
             , fee
             , settlement_rate
          from tb_cms_product_settlement
         where item_type in ('normal', 'discount', 'comped')
    ),
    tmp_contract_offer_amount_list_summary as (
        select z.product_id
             , z.offer_price
          from tb_product_contract_offer z
         where z.use_yn = 'Y'
           and z.author_accept_yn = 'Y'
    )
    select t.product_id
         , t.item_type
         , t.device_type
         , t.sum_total_sales_price
         , t.fee
         , (t.sum_total_sales_price - t.fee) as net_sales_price -- 순매출액(매출액 - 결제수수료)
         , (t.sum_total_sales_price - t.fee - round(t.sum_total_sales_price * (t.settlement_rate / 100), 0)) as taxable_price -- 공급가액(순매출액 - 플랫폼수익)
         , 0 as vat_price -- 부가세액(정산액 - 공급가액). 현재 0 고정
         , round((t.sum_total_sales_price - t.fee - round(t.sum_total_sales_price * (t.settlement_rate / 100), 0)) / 1.1, 0) as settlement_price -- 정산액(공급가액 / 1.1)
         , round(t.sum_total_sales_price * (t.settlement_rate / 100), 0) as platform_revenue -- 플랫폼수익(라이크노벨 수익)
         , t.privious_offer_amount -- 당월 선계약금잔액
         , (t.privious_offer_amount - round((t.sum_total_sales_price - t.fee - round(t.sum_total_sales_price * (t.settlement_rate / 100), 0)) / 1.1, 0)) as current_offer_amount -- 잔여계약금(정산후 잔액)
         , case when (t.privious_offer_amount - round((t.sum_total_sales_price - t.fee - round(t.sum_total_sales_price * (t.settlement_rate / 100), 0)) / 1.1, 0)) < 0
                then abs((t.privious_offer_amount - round((t.sum_total_sales_price - t.fee - round(t.sum_total_sales_price * (t.settlement_rate / 100), 0)) / 1.1, 0)))
                else 0
            end as final_settlement_price -- 최종 정산액
         , 0 as created_id
         , 0 as updated_id
     from (
        select a.product_id
             , c.item_type
             , c.device_type
             , case when c.item_type = 'normal' and c.device_type = 'web' then b.sum_normal_price_web - b.sum_refund_normal_price_web
                    when c.item_type = 'normal' and c.device_type = 'playstore' then b.sum_normal_price_playstore - b.sum_refund_normal_price_playstore
                    when c.item_type = 'normal' and c.device_type = 'ios' then b.sum_normal_price_ios - b.sum_refund_normal_price_ios
                    when c.item_type = 'normal' and c.device_type = 'onestore' then b.sum_normal_price_onestore - b.sum_refund_normal_price_onestore
                    when c.item_type = 'discount' and c.device_type = 'web' then b.sum_discount_price_web - b.sum_refund_discount_price_web
                    when c.item_type = 'discount' and c.device_type = 'playstore' then b.sum_discount_price_playstore - b.sum_refund_discount_price_playstore
                    when c.item_type = 'discount' and c.device_type = 'ios' then b.sum_discount_price_ios - b.sum_refund_discount_price_ios
                    when c.item_type = 'discount' and c.device_type = 'onestore' then b.sum_discount_price_onestore - b.sum_refund_discount_price_onestore
                    when c.item_type = 'comped' and c.device_type = 'web' then b.sum_comped_ticket_price_web - b.sum_refund_comped_ticket_price_web
                    when c.item_type = 'comped' and c.device_type = 'playstore' then b.sum_comped_ticket_price_playstore - b.sum_refund_comped_ticket_price_playstore
                    when c.item_type = 'comped' and c.device_type = 'ios' then b.sum_comped_ticket_price_ios - b.sum_refund_comped_ticket_price_ios
                    when c.item_type = 'comped' and c.device_type = 'onestore' then b.sum_comped_ticket_price_onestore - b.sum_refund_comped_ticket_price_onestore
                    else 0
                end as sum_total_sales_price
             , round(c.fee / 100, 0) as fee
             , c.settlement_rate
             , case when d.privious_offer_amount is null then e.offer_price
                    else coalesce(d.current_offer_amount, 0)
                end as privious_offer_amount -- 당월 선계약금잔액
          from tb_batch_daily_product_info_summary a
         inner join tmp_product_settlement_summary b on a.product_id = b.product_id
         inner join tmp_product_settlement_list_summary c on a.product_id = c.product_id
          left join tb_ptn_product_settlement d on a.product_id = d.product_id
           and d.created_date >= date_sub(curdate(), interval 1 month) - interval day(curdate()) - 1 day
           and d.created_date < curdate()
          left join tmp_contract_offer_amount_list_summary e on a.product_id = e.product_id
        ) t
    ) m
 where m.product_id is not null
;

-- 기존 작품별 월매출 및 월별 정산용 임시 합산 데이터 삭제(한달치)
delete from tb_ptn_product_sales_temp_summary
      where created_date < curdate()
;

-- 선계약금 차감 조회
insert into tb_ptn_product_contract_offer_deduction (product_id, title, author_nickname, contract_type, cp_company_name, offer_amount, privious_offer_amount, settlement_price, current_offer_amount, created_id, updated_id)
with tmp_contract_offer_settlement_summary as (
    select z.product_id
         , z.offer_price
         , z.author_profit
         , z.offer_profit
      from tb_product_contract_offer z
     where z.use_yn = 'Y'
       and z.author_accept_yn = 'Y'
)
select distinct a.product_id
     , a.title
     , a.author_nickname
     , a.contract_type
     , a.cp_company_name
     , b.offer_price -- 발행 계약금
     , c.privious_offer_amount -- 당월 계약금 잔액
     , c.settlement_price -- 정산액
     , c.current_offer_amount -- 정산 후 잔액
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tmp_contract_offer_settlement_summary b on a.product_id = b.product_id
 inner join tb_ptn_product_settlement c on a.product_id = c.product_id
;

-- 후원 및 기타 정산
insert into tb_ptn_income_settlement (product_id, item_type, device_type, sum_income_price, total_fee_rate, sum_income_price_exclude_fee, withholding_tax_rate, sum_income_price_final, created_id, updated_id)
with tmp_income_settlement_summary as (
    -- 한달치
    select product_id
         , item_type
         , device_type
         , sum(sum_income_price) as sum_income_price
      from tb_ptn_income_settlement_temp_summary
     where created_date >= date_sub(curdate(), interval 1 month) - interval day(curdate()) - 1 day
       and created_date < curdate()
     group by product_id, item_type, device_type
)
select a.product_id
     , b.item_type
     , b.device_type
     , b.sum_income_price
     , (c.fee + (100 - c.settlement_rate)) as total_fee_rate -- 결제 수수료 + 플랫폼 수수료
     , round(b.sum_income_price * (100 - (c.fee + (100 - c.settlement_rate))) / 100, 1) as sum_income_price_exclude_fee
     , 3.3 as withholding_tax_rate
     , round(round(b.sum_income_price * (100 - (c.fee + (100 - c.settlement_rate))) / 100, 1) * 0.967, 1) as sum_income_price_final
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tmp_income_settlement_summary b on a.product_id = b.product_id
 inner join tb_cms_product_settlement c on a.product_id = c.product_id
   and b.item_type = c.item_type
   and b.device_type = c.device_type
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'partner_report_monthly_batch.sh'
;

commit;

