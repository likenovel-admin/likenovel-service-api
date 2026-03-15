-- Normalize legacy reader-of-prev statuses to the current ing/stop model.

update tb_direct_promotion
   set status = 'stop'
     , num_of_ticket_per_person = 0
     , updated_id = 0
     , updated_date = now()
 where `type` = 'reader-of-prev'
   and status = 'end'
;

update tb_direct_promotion
   set status = case
                  when coalesce(num_of_ticket_per_person, 0) > 0 then 'ing'
                  else 'stop'
                end
     , num_of_ticket_per_person = case
                                    when coalesce(num_of_ticket_per_person, 0) > 0 then coalesce(num_of_ticket_per_person, 0)
                                    else 0
                                  end
     , updated_id = 0
     , updated_date = now()
 where `type` = 'reader-of-prev'
   and status = 'pending'
;
