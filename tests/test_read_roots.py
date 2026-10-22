"An embedding host opens a reference checkout for reading only: the agent is told, searches it, and never writes it."
from ramabana.agent import mk_agent
from ramabana.tools import failed


def test_an_agent_searches_a_read_root_and_never_writes_it(tmp_path):
    work, ref = tmp_path/'work', tmp_path/'ref'
    work.mkdir(); ref.mkdir()
    (ref/'source.py').write_text('def lawful_source(): pass\n')
    a, host = mk_agent([str(work)], read_roots=[str(ref)], approve='auto', cfg=tmp_path/'cfg', web=False, extensions=False, subagents=False)
    try:
        assert host.read_roots == [str(ref.resolve())] and str(ref.resolve()) not in host.roots
        sp = a.system_prompt()
        assert str(ref.resolve()) in sp
        tools = {t.__name__: t for t in a.tools}
        assert 'lawful_source' in tools['grep']('lawful_source')
        assert failed(tools['create_file'](str(ref/'x.py'), 'y = 1')) and not (ref/'x.py').exists()
    finally: a.close()
