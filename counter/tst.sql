select t, airline, count(*)
    from (
        select distinct callsign, airline, timestamp/3600 as t from flights
            where airline in 
            (
                select airline
                    from (
                        select distinct callsign, airline, date from flights
                        ) as counts
                    group by airline
                    order by count(*) desc limit 10
            )
        ) as counts 
    group by airline, t 
    order by t, airline
    ;
    