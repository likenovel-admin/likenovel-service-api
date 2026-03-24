-- 문피아식 장르 체계 정렬:
-- 1) 1차/2차 모두 같은 장르 목록 사용
-- 2) 제외 장르 및 비표준 장르 비활성화
-- 3) 최종 활성 장르 16개를 category_id=1, major_genre_yn='Y'로 고정

UPDATE tb_standard_keyword
   SET keyword_name = '판타지'
     , updated_date = NOW()
 WHERE category_id = 1
   AND keyword_name = '정통판타지';

UPDATE tb_standard_keyword
   SET keyword_name = '퓨전'
     , updated_date = NOW()
 WHERE category_id = 1
   AND keyword_name = '퓨전판타지';

INSERT IGNORE INTO tb_standard_keyword (
    keyword_name,
    major_genre_yn,
    filter_yn,
    category_id,
    use_yn,
    created_id,
    updated_id
)
VALUES
    ('퓨전', 'Y', 'Y', 1, 'Y', 0, 0),
    ('스포츠', 'Y', 'Y', 1, 'Y', 0, 0),
    ('전쟁·밀리터리', 'Y', 'Y', 1, 'Y', 0, 0),
    ('추리', 'Y', 'Y', 1, 'Y', 0, 0),
    ('공포·미스테리', 'Y', 'Y', 1, 'Y', 0, 0),
    ('일반소설', 'Y', 'Y', 1, 'Y', 0, 0),
    ('팬픽·패러디', 'Y', 'Y', 1, 'Y', 0, 0);

UPDATE tb_standard_keyword
   SET major_genre_yn = 'Y'
     , filter_yn = 'Y'
     , use_yn = 'Y'
     , updated_date = NOW()
 WHERE category_id = 1
   AND keyword_name IN (
       '무협',
       '판타지',
       '퓨전',
       '게임',
       '스포츠',
       '로맨스',
       '라이트노벨',
       '현대판타지',
       '대체역사',
       '전쟁·밀리터리',
       'SF',
       '추리',
       '공포·미스테리',
       '일반소설',
       '드라마',
       '팬픽·패러디'
   );

UPDATE tb_standard_keyword
   SET use_yn = 'N'
     , updated_date = NOW()
 WHERE category_id = 1
   AND keyword_name NOT IN (
       '무협',
       '판타지',
       '퓨전',
       '게임',
       '스포츠',
       '로맨스',
       '라이트노벨',
       '현대판타지',
       '대체역사',
       '전쟁·밀리터리',
       'SF',
       '추리',
       '공포·미스테리',
       '일반소설',
       '드라마',
       '팬픽·패러디'
   );
