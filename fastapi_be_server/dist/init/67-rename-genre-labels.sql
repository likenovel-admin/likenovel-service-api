-- 1차 장르 라벨 변경: 판타지 → 정통판타지, 퓨전 → 퓨전판타지

update tb_standard_keyword
   set keyword_name = '정통판타지'
     , updated_date = now()
 where keyword_name = '판타지'
   and major_genre_yn = 'Y'
;

update tb_standard_keyword
   set keyword_name = '퓨전판타지'
     , updated_date = now()
 where keyword_name = '퓨전'
   and major_genre_yn = 'Y'
;
