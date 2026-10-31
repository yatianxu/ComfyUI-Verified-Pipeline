"""Single-entry, sequential ComfyUI production controller for the approved Thriller edit.

Native H3/SAM prompts run on 8188 AFTER the scheduling graph has returned. Never
wait for a prompt on the executor thread which is meant to execute that prompt.
"""
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, subprocess, sys, time, traceback, uuid
import urllib.request

R = Path(__file__).resolve().parent
if not (R / 'production/runtime').exists():
    R = next(p / '素材/thriller' for p in R.parents if (p / '素材/thriller/production/runtime').exists())
P = R / 'production/runtime'
D = R / 'film/span_506_635/v3_production'
N = D.parent / 'v4_closeups'
DELIVERY = R.parents[1] / '最终交付/Thriller_万圣节名人群舞成片'
HOME = DELIVERY / '一体化总工作流'
MANIFEST = HOME / 'pipeline_manifest.json'
STATE = HOME / '运行记录'
URL = 'http://127.0.0.1:8188'
PYTHON = Path(sys.executable)
STAGES = ['01 素材与依赖检查', '02 灰模整角色H3生成', '03 SAM3跟踪遮罩',
          '04 原129秒底片合成', '05 鬼屋前截止最终合成', '06 完整解码与音画核验']


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, value):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, p)


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def api(path, data=None):
    req = urllib.request.Request(URL + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=30))


def compile_manifest():
    """Freeze actually selected APIs, including the 18 approved base repairs."""
    old = DELIVERY / '129秒完整版'
    new = DELIVERY / '鬼屋前截止_特写增强版'
    source = next(R.glob('*4K*.mp4'))
    import numpy as np
    jobs = []
    base = read(D / 'generation_state.json')['chunks']
    base_records = {x['job']: x['recorded_api'] for x in read(D / 'workbench_production_parameter_check.json')['jobs']}
    bm = read(D / 'matte_state.json')
    for key, chunk in base.items():
        for role, cfg in chunk['roles'].items():
            job = 'Prod129_' + key + '_' + role
            jobs.append(dict(job=job, group='base', cfg=cfg, api=base_records[job],
                             matte=bm[key + '_' + role], source_masks=str(D / chunk['shot'] / (role + '_source_masks.npz'))))
    vm = read(N / 'matte_state.json')
    runs = {x['job']: x['actual_api'] for x in read(new / '工作流与运行记录/新增运行来源.json')['runs']}
    for key, cfg in read(N / 'selected_jobs.json')['jobs'].items():
        jobs.append(dict(job='V4_' + key, group='inserts', cfg=cfg, api=runs['V4_' + key],
                         matte=vm[key], source_masks=cfg['source_masks']))
    assert len(jobs) == 146
    # Delivered NPZ copies are recovery sources, not replacements for the live paths.
    copies = {}
    for root in [old / '跟踪遮罩', new / '新增跟踪遮罩']:
        for p in root.rglob('*.npz'):
            copies.setdefault(sha(p), str(p))
    inputs, generated = {}, {}
    for job in jobs:
        g = read(job['api'])
        job['api_sha256'] = sha(job['api'])
        for node, field in [('152', 'file'), ('300', 'file'), ('322', 'file'), ('137', 'image')]:
            p = P / 'input' / g[node]['inputs'][field]
            inputs[str(p)] = sha(p)
        for p in [Path(job['cfg']['crop_masks']), Path(job['source_masks'])]:
            inputs[str(p)] = sha(p)
        cfg = job['cfg']
        if cfg.get('background_plate'):
            inputs[cfg['background_plate']] = sha(cfg['background_plate'])
        raw, mask = Path(cfg['raw']), Path(job['matte']['mask'])
        assert sha(raw) == job['matte']['raw_sha256']
        generated[str(raw)] = dict(sha256=sha(raw), kind='raw', backup=None)
        h = sha(mask)
        with np.load(mask, allow_pickle=False) as z:
            metadata = {k:dict(dtype=str(z[k].dtype), value=z[k].tolist()) for k in z.files if k != 'masks'}
            generated[str(mask)] = dict(sha256=h, kind='matte', backup=copies.get(h),
                mask_pixels_sha256=hashlib.sha256(z['masks'].tobytes()).hexdigest(),
                archive_order=z.files, metadata=metadata)
        overrides = read(D/'matte_seed_overrides.json') if (D/'matte_seed_overrides.json').exists() else {}
        job['sam_threshold'] = overrides.get(job['job'].removeprefix('Prod129_'),{}).get('threshold',.5)
    for group in jobs:
        group['raw_sha256'] = generated[group['cfg']['raw']]['sha256']
    protected = [D / 'generation_state.json', D / 'matte_state.json', D / 'reaction_candidates.json',
                 D / 'composite_settings129.json', D / 'matting_complete.json', D / 'repair_review_gate.json',
                 N / 'selected_jobs.json', N / 'matte_state.json', N / 'matte_complete.json',
                 N / 'visual_approval.json', N / 'end_decision.json', N / 'tail_plate_alignment_passthrough.json']
    inputs.update({str(p): sha(p) for p in protected})
    films = {}
    for directory, proof in [(old, read(D / 'final_decode_verification.json')), (new, read(N / 'final_verification.json'))]:
        for name, info in proof['files'].items():
            films[str(directory / name)] = dict(sha256=info['sha256'], proof=str(directory / '完整解码与音画核验.json'))
    manifest = dict(version=1, project=str(R), source=dict(path=str(source), bytes=source.stat().st_size,
        mtime_ns=source.stat().st_mtime_ns), jobs=jobs, inputs=inputs, generated=generated, films=films,
        scripts={name: sha(R / name) for name in ['integrated_pipeline.py', 'compose_production129.py', 'v4_compose.py', 'v4_verify.py']},
        recovery_copies=copies, start_seconds=506, frames=3173, fps=24, stages=STAGES)
    save(MANIFEST, manifest)
    print('Frozen', len(jobs), 'actual native H3 jobs;', len(inputs), 'prepared inputs;', len(generated), 'outputs', flush=True)


class Pipeline:
    def __init__(self, request):
        self.request = request
        self.run = Path(request['run_dir']).resolve()
        if not self.run.is_relative_to(STATE.resolve()):
            raise ValueError('Run directory must stay inside project pipeline records')
        self.run.mkdir(parents=True, exist_ok=True)
        self.manifest = read(MANIFEST)
        self.base_dir = DELIVERY / '129秒完整版'
        self.final_dir = DELIVERY / '鬼屋前截止_特写增强版'
        self.status = dict(run_id=self.run.name, state='running', current_stage='', stages=[],
                           started=time.time(), run_dir=str(self.run), completed_jobs=0, total_jobs=146)
        self.active_prompt = None

    def report(self, **values):
        self.status.update(values)
        self.status['updated'] = time.time()
        save(self.run / 'status.json', self.status)
        save(STATE / 'latest.json', self.status)
        print(self.status.get('current_stage'), self.status.get('message', ''), flush=True)

    def check_cancel(self):
        if (self.run / 'cancel.request').exists():
            # Do not globally interrupt a shared executor; an already submitted native
            # job finishes, then the next role/stage is not submitted.
            raise InterruptedError('已停止后续任务；已提交的单个原生任务允许正常结束')

    def ensure(self, path, item):
        p = Path(path)
        if p.is_file():
            if sha(p) != item['sha256']:
                raise RuntimeError('已批准文件发生变化，禁止默默沿用旧遮罩/审核：' + str(p))
            return 'reused'
        backup = item.get('backup')
        if backup and Path(backup).is_file() and sha(backup) == item['sha256']:
            self.check_cancel()
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, p)
            return 'restored'
        return 'missing'

    def native(self, graph, label):
        """Submit from this detached controller, never from the Comfy executor."""
        self.check_cancel()
        result = api('/prompt', dict(prompt=graph, client_id='ThrillerIntegrated-' + self.run.name))
        if result.get('node_errors') or not result.get('prompt_id'):
            raise RuntimeError(result)
        pid = result['prompt_id']
        save(self.run / (label + '.submitted.json'), dict(prompt_id=pid, graph=graph))
        self.active_prompt = pid
        self.report(active_prompt=pid, message=label + ' 原生节点执行中')
        deadline = time.monotonic() + 7200
        while time.monotonic() < deadline:
            h = api('/history/' + pid).get(pid)
            if h:
                save(self.run / (label + '.history.json'), h)
                if h['status']['status_str'] != 'success':
                    raise RuntimeError('原生任务失败：' + str(h['status']))
                self.active_prompt = None
                self.check_cancel()
                return h
            # A cancellation never means the GPU job has stopped. Drain the owned
            # prompt first, preserving the single-GPU model-stage boundary.
            time.sleep(2)
        raise TimeoutError('原生任务超时；保留prompt_id供恢复查询：' + pid)

    def preflight(self):
        m = self.manifest
        src = Path(m['source']['path']).stat()
        assert src.st_size == m['source']['bytes'] and src.st_mtime_ns == m['source']['mtime_ns'], '原MV发生变化'
        for p, h in m['inputs'].items():
            self.check_cancel()
            if not Path(p).is_file() and h in m.get('recovery_copies',{}):
                backup = Path(m['recovery_copies'][h])
                if backup.is_file() and sha(backup) == h:
                    Path(p).parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(backup,p)
            if not Path(p).is_file() or sha(p) != h:
                raise RuntimeError('素材或已批准配置不完整/已修改：' + p)
        for name, h in m['scripts'].items():
            if sha(R / name) != h:
                raise RuntimeError('执行脚本与整合清单不一致：' + name)
        catalog = api('/object_info')
        for j in m['jobs']:
            assert sha(j['api']) == j['api_sha256'], j['job']
            missing = [v['class_type'] for v in read(j['api']).values() if v['class_type'] not in catalog]
            if missing:
                raise RuntimeError('缺少原生节点：' + str(missing))
        self.report(message=f'素材/配置 {len(m["inputs"])} 项一致；146个实际API依赖齐全；原MV按文件属性核对')

    def generation(self):
        for i, job in enumerate(self.manifest['jobs']):
            self.check_cancel()
            p = Path(job['cfg']['raw'])
            result = self.ensure(p, self.manifest['generated'][str(p)])
            if result == 'missing':
                g = copy.deepcopy(read(job['api']))
                prefix = 'ThrillerIntegrated/' + self.run.name + '/' + job['job']
                g['307']['inputs']['filename_prefix'] = prefix
                hist = self.native(g, job['job'])
                import generate_production129 as gen
                candidate = Path(gen.raw_path(hist))
                save(self.run / (job['job'] + '.candidate.json'), dict(raw=str(candidate), expected=str(p),
                    sha256=sha(candidate), expected_sha256=job['raw_sha256']))
                if sha(candidate) != job['raw_sha256']:
                    raise RuntimeError('重生成结果需重新复核，已保存候选，禁止把旧遮罩/审核套在新视频：' + str(candidate))
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, p)
                result = 'regenerated_exact'
            self.report(completed_jobs=i + 1, message=f'{i+1}/146 {job["job"]}: {result}')

    def mattes(self):
        import numpy as np
        restored = 0
        for i, job in enumerate(self.manifest['jobs']):
            self.check_cancel()
            # An unchanged raw is essential even when only the mask stage is selected.
            if sha(job['cfg']['raw']) != job['matte']['raw_sha256']:
                raise RuntimeError('遮罩与raw不匹配：' + job['job'])
            p = Path(job['matte']['mask'])
            outcome = self.ensure(p, self.manifest['generated'][str(p)])
            if outcome == 'missing':
                self.regenerate_matte(job, p)
                outcome = 'regenerated_exact'
            restored += outcome == 'restored'
            with np.load(p, allow_pickle=False) as z:
                if str(z['raw_sha256']) != job['matte']['raw_sha256'] or len(z['masks']) != job['cfg']['frames']:
                    raise RuntimeError('遮罩帧数/raw绑定失效：' + job['job'])
        self.report(message=f'146/146生成后全身遮罩已核对；从交付缓存恢复{restored}份；保留Mark已审修边')

    def regenerate_matte(self, job, destination):
        """Native bidirectional SAM, with explicit review if original pixels differ."""
        if job['matte'].get('component_cleanup'):
            raise RuntimeError('Mark人工修边缓存和交付备份同时缺失，需要重新修边复核')
        import numpy as np
        from PIL import Image
        import production129_common as common
        cfg = job['cfg']
        api('/free',dict(unload_models=True,free_memory=True))
        seq = list(common.frames(cfg['raw']))
        seed = int(job['matte']['seed_frame'])
        masks = np.load(cfg['crop_masks'])['masks']
        yy, xx = np.where(masks[seed] > 0)
        box = dict(x=int(xx.min()), y=int(yy.min()), width=int(xx.max()-xx.min()+1), height=int(yy.max()-yy.min()+1))
        token = 'Integrated_' + self.run.name + '_' + job['job']
        image = token + '.png'
        Image.fromarray(seq[seed]).save(P / 'input' / image)
        parts = {}
        for direction, frames in [('fwd', seq[seed:]), ('rev', seq[seed::-1])]:
            video = token + '_' + direction + '.mp4'
            common.write_video(P / 'input' / video, frames)
            prefix = 'ThrillerIntegrated/mattes/' + token + '_' + direction
            graph = common.native_track(video, image, prefix)
            graph['5'] = dict(class_type='SAM3_Detect', inputs=dict(model=['1',0], image=['4',0], threshold=job['sam_threshold'],
                refine_iterations=1, individual_masks=False, bboxes=box))
            self.native(graph, token + '_' + direction)
            parts[direction] = common.packed_masks(P / 'output' / (prefix + '.npz'))
        m = np.concatenate([parts['rev'][::-1][:-1], parts['fwd']], 0)
        candidate = self.run / (job['job'] + '_candidate_masks.npz')
        record = self.manifest['generated'][str(destination)]
        metadata = {k:np.array(v['value'],dtype=v['dtype']) for k,v in record['metadata'].items()}
        values = {'masks':m,**metadata}
        np.savez_compressed(candidate, **{k:values[k] for k in record['archive_order']})
        if hashlib.sha256(m.tobytes()).hexdigest() != record['mask_pixels_sha256']:
            raise RuntimeError('SAM3候选已生成，需要新的画面复核：' + str(candidate))
        if sha(candidate) != record['sha256']:
            raise RuntimeError('SAM3像素一致但缓存序列化不同，已保留候选；请恢复已批准备份：' + str(candidate))
        shutil.copy2(candidate, destination)

    def subprocess_stage(self, module, destination, base=None):
        payload = dict(module=module, destination=str(destination), base=str(base) if base else None)
        cfg = self.run / (module + '.json')
        save(cfg, payload)
        log = self.run / (module + '.log')
        with log.open('w', encoding='utf-8') as f:
            child = subprocess.Popen([str(PYTHON), '-u', str(R / 'integrated_pipeline.py'), 'child', str(cfg)],
                                     cwd=str(R), stdout=f, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.report(child_pid=child.pid, message=module + ' 执行中；日志 ' + str(log))
            while child.poll() is None:
                # Cancellation is honored at stage boundary. Do not kill an encoder
                # midway or leave detached ffmpeg processes writing partial outputs.
                time.sleep(2)
            if child.returncode:
                raise RuntimeError(module + ' 失败；请查看 ' + str(log))
        self.check_cancel()

    def film_cache_ok(self, directory):
        records = {p: h for p, h in self.manifest['films'].items() if Path(p).parent == directory}
        return len(records) == 2 and all(Path(p).is_file() and sha(p) == h['sha256'] for p,h in records.items())

    def compose(self, base=False):
        original = DELIVERY / ('129秒完整版' if base else '鬼屋前截止_特写增强版')
        if self.request.get('reencode') or not self.film_cache_ok(original) or (not base and self.base_dir != DELIVERY / '129秒完整版'):
            # Fresh exports always go into this run, leaving accepted masters intact.
            dest = self.run / ('129秒底片' if base else '最终成片')
            dest.mkdir(exist_ok=True)
            self.subprocess_stage('compose_production129' if base else 'v4_compose', dest,
                                  self.base_dir / 'Thriller_万圣节名人群舞_129秒_4K.mp4')
            if base:
                self.base_dir = dest
            else:
                self.final_dir = dest
        else:
            self.report(message='SHA一致，复用已核验的' + ('129秒底片' if base else '132.21秒4K/1080p成片'))

    def verify(self):
        if self.request.get('full_decode') or self.final_dir != DELIVERY / '鬼屋前截止_特写增强版':
            self.subprocess_stage('v4_verify', self.final_dir)
            proof = read(self.final_dir / '完整解码与音画核验.json')
        else:
            proof = read(self.final_dir / '完整解码与音画核验.json')
        for name, item in proof['files'].items():
            if sha(self.final_dir / name) != item['sha256']:
                raise RuntimeError('解码核验证明与成片SHA不符：' + name)
            if item['frames'] != 3173 or item['corrupt_frames'] or any(abs(x['offset_ms']) > 1 for x in item['audio_sync']):
                raise RuntimeError('成片未通过帧数/解码/音画检查')
        save(self.run / '总流程验收.json', dict(passed=True, proof=proof, final_directory=str(self.final_dir),
             full_decode_rerun=bool(self.request.get('full_decode') or self.final_dir != DELIVERY / '鬼屋前截止_特写增强版'),
             visual_review='Existing approved raw/matte SHA reused; fresh exports require final visual review',
             pipeline_manifest_sha256=sha(MANIFEST)))
        self.report(message='3173帧/24fps；双输出SHA与完整解码/音画证明一致', outputs=[str(self.final_dir/name) for name in proof['files']])

    def execute(self):
        STATE.mkdir(parents=True, exist_ok=True)
        lock = STATE / 'pipeline.lock'
        # OS lock is released even if the process crashes. The marker remains for diagnosis.
        import msvcrt
        with lock.open('a+b') as handle:
            if lock.stat().st_size == 0:
                handle.write(b'0');handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('已有总流程运行，禁止并行抢占同一GPU/输出')
            try:
                self.report(pid=os.getpid(), message='等待总流程调度图退出Comfy执行队列')
                # If the launch graph ran on 8188, submitting native prompts before it
                # finishes is safe only asynchronously. Wait for idle explicitly.
                for _ in range(120):
                    self.check_cancel()
                    queue = api('/queue')
                    if not queue['queue_running'] and not queue['queue_pending']:
                        break
                    time.sleep(1)
                else:
                    raise TimeoutError('8188持续繁忙；总流程未插入原生任务')
                if self.request['start'] > 1:
                    # A partial run still cannot bypass changed-input detection.
                    self.report(current_stage='开始前一致性检查',message='分阶段运行前核对冻结素材与配置')
                    self.preflight()
                actions = [self.preflight, self.generation, self.mattes, lambda:self.compose(True), self.compose, self.verify]
                for i, action in enumerate(actions, 1):
                    if i < self.request['start'] or i > self.request['end']:
                        continue
                    self.check_cancel()
                    self.report(current_stage=STAGES[i-1], stage_index=i, message='开始')
                    action()
                    self.status['stages'].append(dict(index=i, stage=STAGES[i-1], state='complete'))
                self.report(state='complete', message='所选阶段执行完毕', finished=time.time())
            except InterruptedError as e:
                self.report(state='cancelled', message=str(e), finished=time.time())
            except Exception as e:
                self.report(state='failed', message=str(e), traceback=traceback.format_exc(), finished=time.time())
                raise
            finally:
                handle.seek(0);msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def child(config):
    import importlib
    cfg = read(config)
    module = importlib.import_module(cfg['module'])
    module.DEST = Path(cfg['destination'])
    # Avoid replacing the canonical production proofs when making fresh exports.
    if cfg['module'] in ['compose_production129','v4_compose','v4_verify']:
        original_save = module.save
        def save_run(path, value):
            p = Path(path)
            if p.parent in [D, N]:
                p = Path(config).parent / ('fresh_' + p.name)
            original_save(p, value)
        module.save = save_run
    if cfg.get('base') and cfg['module'] == 'v4_compose':
        module.BASE = Path(cfg['base'])
    module.main()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['build','run','child'])
    ap.add_argument('path', nargs='?')
    args = ap.parse_args()
    if args.command == 'build':
        compile_manifest()
    elif args.command == 'child':
        child(args.path)
    else:
        Pipeline(read(args.path)).execute()
