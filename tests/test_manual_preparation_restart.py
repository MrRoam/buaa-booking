import pytest
from buaa_booking.journal import Journal


def test_only_never_submitted_preparation_can_be_restarted(tmp_path):
    j = Journal(tmp_path)
    j.save('safe', 'finished', attempts=0)
    assert j.resume_unsubmitted('safe')['status'] == 'preparation_retry'
    assert j.db.execute('SELECT COUNT(*) FROM events WHERE job_key=?', ('safe',)).fetchone()[0] == 2
    for key, values in [('unknown', {'status':'unknown', 'attempts':0}),
                        ('sent', {'status':'finished', 'attempts':1}),
                        ('trade', {'status':'finished', 'attempts':0, 'trade_no':'ORDER'})]:
        j.save(key, **values)
        with pytest.raises(RuntimeError):
            j.resume_unsubmitted(key)
    j.save('trace', 'finished', attempts=0)
    j.trace('trace', 'submit_start')
    with pytest.raises(RuntimeError):
        j.resume_unsubmitted('trace')
    j.close()
