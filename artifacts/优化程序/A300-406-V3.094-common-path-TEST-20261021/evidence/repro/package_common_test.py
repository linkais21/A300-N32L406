"""Assemble the reviewable App-only test delivery without production writes."""
from pathlib import Path
import runpy, hashlib, json, shutil, difflib, subprocess, struct, zlib, zipfile

m=runpy.run_path(str(Path(__file__).with_name('optimize_isolated.py')))
OUT=m['OUT'];SOURCE=m['SOURCE'];BASE=OUT/'source-baseline';OPT=OUT/'source-optimized'
save=m['save'];digest=m['digest']

def main():
    tests=json.loads((OUT/'evidence/source-optimized-tests.json').read_text())
    assert len(tests)>70 and not any(t['exit_code'] or t['skip'] for t in tests),tests
    before=json.loads((OUT/'evidence/production-before.json').read_text(encoding='utf-8'))
    # Restore the baseline fixtures byte-for-byte to the actual frozen input.
    # Keep necessary environment/test assertion fixes only in the candidate.
    for name in before:
        if not name.startswith('tools/tests/') or not (BASE/name).is_file():continue
        expected=before[name]
        if digest(BASE/name)==expected:continue
        data=(SOURCE/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:
            assert name=='tools/tests/test_work_mode_jt808_contract.py',name
            data=data.replace(b'r"\\s*historical_position\\s*,\\s*cfg_get\\(\\)\\s*->\\s*mileage_m\\s*\\)", wrapper)',b'r"\\s*historical_position\\s*\\)", wrapper)')
            # The frozen pre-existing test had mixed/changed line endings and
            # was concurrently edited. Preserve its old four-argument assertion
            # semantically; do not claim byte identity for this test fixture.
            assert b'r"\\s*historical_position\\s*\\)", wrapper)' in data,name
        (BASE/name).write_bytes(data)
    diff=[];production_diff=[];test_diff=[];changes=[]
    for p in sorted(OPT.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(OPT)
        if any(x.startswith('build') or x in ('__pycache__','.pytest_cache') for x in rel.parts[:-1]):continue
        old=BASE/rel
        if old.is_file() and p.read_bytes()!=old.read_bytes():
            patch=''.join(difflib.unified_diff(old.read_text(encoding='utf-8').splitlines(True),p.read_text(encoding='utf-8').splitlines(True),fromfile='a/'+rel.as_posix(),tofile='b/'+rel.as_posix()))
            diff.append(patch);changes.append(rel.as_posix())
            (test_diff if rel.parts[0]=='tools' else production_diff).append(patch)
    assert [x for x in changes if x.startswith('src/')] == ['src/at_config.c','src/ec800m.c','src/f39_reply.c']
    assert not [x for x in changes if x.startswith(('include/','bootloader/','ldscript/')) or x.lower()=='makefile']
    (OUT/'optimization.patch').write_text(''.join(production_diff),encoding='utf-8')
    (OUT/'test-environment.patch').write_text(''.join(test_diff),encoding='utf-8')
    checks=[]
    for rel in ('src/at_config.c','src/ec800m.c','src/f39_reply.c'):
        command=['git','-c','core.autocrlf=false','-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--no-index','--check','--',str(BASE/rel),str(OPT/rel)]
        r=subprocess.run(command,capture_output=True)
        assert r.returncode in (0,1) and not r.stdout.strip() and not r.stderr.strip(),(rel,r.stdout,r.stderr)
        checks.append({'path':rel,'exit_code':r.returncode,'no_whitespace_findings':True,'note':'--no-index may return 1 for differing files; --check output is empty.'})
    save(OUT/'evidence/diff-check.json',checks)
    review='''# 最终差异自审

范围：冻结的含未提交改动V3.094输入到独立source-optimized，不使用Git HEAD代替基线。三个产品C文件的实际差异逐处审查，未修改Boot/布局/权限/持久化/验签接口。未合入生产。

- at_config：先按原规则大写，然后13项固定名称表精确strcmp；编号与原分支逐项对应；未知命令0仍走原错误路径。参数个数、转换、单位、保存和调用保持原分支。差分回放比较全部命令名/大小写/分隔符/缺参/多参/边界数字，捕获server、timer、heartbeat、relay真实调用参数。
- ec800m：仅QISEND和QICLOSE的通道格式从%d转%u并显式转unsigned。两处均在ch<EC800M_CH_MAX校验之后，合法通道0..3输出字节一致；超时、AT所有权、失败恢复、代次、日志均保留。没有合并TCP/UDP状态机。
- f39_reply：仅把原三元表达式成功/失败映射抽成reply_result；reply_append仍只调用一次，失败仍清空并生成相同reply-too-long文本。涉及参数均为稳定指针/名称，没有因C实参求值顺序引入副作用。原继电器安全校验和参数复制保持原实现。
- 参数复制共用方案虽净省32B，但栈预算增加8B，最终撤回；数字/字节序/端点分支试验未净省，未采纳。最终栈2812B、静态15964B与冻结基线相同。
- 检查版本身份、链接器、Bootloader、内外Flash布局、签名源、持久化源与基线一致；git diff --no-index --check通过。未发现本轮改动的阻断性问题。

验证：78项host tests、F39每版本12488次/串口4416次差分执行、ARM构建、项目release-gate。此为范围内自审；没有独立硬件审查，不等价于实机/HIL或所有出货Boot兼容性证明。资源4KiB目标未满足，维持不合入决定。
'''
    (OUT/'evidence/SCOPED-REVIEW.md').write_text(review,encoding='utf-8')
    repro=OUT/'evidence/repro';repro.mkdir(exist_ok=True)
    # Make the differential harnesses runnable from inside the packaged tree.
    for name in ('validate_common_paths.py','validate_console_paths.py'):
        content=Path(__file__).with_name(name).read_text(encoding='utf-8')
        if name=='validate_common_paths.py':
            content=content.replace("m=runpy.run_path(str(Path(__file__).with_name('optimize_isolated.py')))\nOUT=m['OUT']", "OUT=Path(__file__).resolve().parents[2]")
        (repro/name).write_text(content,encoding='utf-8')
    shutil.copyfile(Path(__file__),repro/'package_common_test.py')

    output=OUT/'firmware';output.mkdir(exist_ok=True)
    final=OPT/'build-common-final'
    for suffix in ('bin','hex','elf','map'):
        target=output/('A300-406-V3.094-common-path-TEST-App.'+suffix)
        shutil.copyfile(final/('a300_firmware.'+suffix),target)
    app=(output/'A300-406-V3.094-common-path-TEST-App.bin').read_bytes()
    cap=json.loads((final/'flash-capacity.json').read_text());basecap=json.loads((BASE/'build-baseline/flash-capacity.json').read_text())
    assert len(app)==106236 and cap['remaining_bytes']==260 and basecap['used_bytes']==106336
    # Check each actual Intel HEX data byte against the delivered BIN and layout.
    address=0;mem={};eof=False
    for line in (output/'A300-406-V3.094-common-path-TEST-App.hex').read_text().splitlines():
        assert line.startswith(':');record=bytes.fromhex(line[1:]);assert sum(record)%256==0
        count=record[0];offset=int.from_bytes(record[1:3],'big');kind=record[3];data=record[4:4+count]
        if kind==0:
            for i,b in enumerate(data):
                a=address+offset+i;assert 0x08006000<=a<0x08020000
                mem[a]=b
        elif kind==4:address=int.from_bytes(data,'big')<<16
        elif kind==1:eof=True
    assert eof and min(mem)==0x08006000
    for a,b in mem.items():assert app[a-0x08006000]==b
    sp,reset=struct.unpack_from('<II',app)
    assert 0x20000000<sp<=0x20006000 and sp%8==0 and reset&1
    assert 0x08006000<=(reset&~1)<0x08006000+len(app)
    # Transport body only: platform signing/version policy remain mandatory.
    header=struct.pack('<IIIII12s',0xA300B007,3094,len(app),zlib.crc32(app)&0xffffffff,0x41333030,bytes(12))
    unsigned=output/'A300-406-V3.094-common-path-TEST-OTA-UNSIGNED.bin'
    unsigned.write_bytes(header+app)
    assert unsigned.read_bytes()[32:]==app
    save(OUT/'evidence/artifact-validation.json',{'hex_bin_equal':True,'hex_min':hex(min(mem)),'hex_max':hex(max(mem)),'hex_bytes':len(mem),'initial_sp':hex(sp),'reset_vector':hex(reset),'ota_header_bytes':32,'ota_body_equal':True,'ota_platform_signature_present':False})
    for name in ('flash-capacity.json','flash-build-profile.json','stack-analysis.json','stack-evidence.json'):
        shutil.copyfile(final/name,OUT/'evidence'/('final-'+name))
    frozen={}
    for rel,expected in before.items():
        p=BASE/rel
        if p.is_file() and not any(x.startswith('build') for x in Path(rel).parts[:-1]):
            frozen[rel]={'sha256':digest(p),'matches_frozen':digest(p)==expected}
    mismatches=[rel for rel,r in frozen.items() if not r['matches_frozen']]
    assert mismatches==['tools/tests/test_work_mode_jt808_contract.py'],mismatches
    save(OUT/'evidence/baseline-snapshot-verification.json',{'files':frozen,'test_fixture_byte_mismatch':mismatches,'compiled_inputs_exact':True,'note':'Only the concurrent test fixture was reconstructed semantically after test-environment edits; original pre-task SHA256 remains in production-before.json. No target C/build inputs differ from the frozen hashes.'})
    after=m['inventory']();changed=[k for k in before.keys()|after.keys() if before.get(k)!=after.get(k)]
    assert not [k for k in changed if k!='tools/tests/test_work_mode_jt808_contract.py'],changed
    save(OUT/'evidence/production-verification.json',{'files_checked':len(before),'changed':changed,'compiled_inputs_and_default_build_unchanged':True,'note':'One existing test assertion was concurrently updated outside this task. This task wrote only the isolated artifact directory and analysis-results.'})
    manifest={'status':'TEST_ONLY_PENDING_HIL','formal_release':False,'production_merge':False,'rtk_included':False,'baseline_version':'V3.094','version_counter':3094,'app_origin':'0x08006000','app_budget_bytes':106496,'baseline_app_bytes':106336,'optimized_app_bytes':106236,'saved_bytes':100,'remaining_bytes':260,'target_headroom_bytes':4096,'target_met':False,'static_ram_bytes':15964,'heap_reservation_bytes':1024,'boot_main_stack_bytes':2812,'nested_exception_bytes':584,'runtime_gap_bytes':4192,'ram_budget_unchanged':True,'changed_source_files':[x for x in changes if x.startswith('src/')],'test_fixture_changes':[x for x in changes if x.startswith('tools/')],'host_tests_passed':len(tests),'differential_executions_per_version':16904,'production_changed_by_task':False,'production_concurrent_changes':changed,'firmware_files':{p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in output.iterdir() if p.is_file()}}
    save(OUT/'manifest.json',manifest)
    readme=f'''# A300-406 V3.094 公共路径优化独立测试版

本包是待实机验证的 App 优化试验版，未正式发布、未合入主仓库、未上传平台、未烧录。未加入 RTK。

## 实测结果

| 项目 | 冻结基线 | 本测试版 |
|---|---:|---:|
| App 占用 | 106336 B | 106236 B |
| App 预算 | 106496 B | 106496 B |
| App 剩余 | 160 B | 260 B |
| 静态 RAM | 15964 B | 15964 B |
| 堆预留 | 1024 B | 1024 B |
| 启动/主路径栈预算 | 2812 B | 2812 B |
| 嵌套异常预算 | 584 B | 584 B |
| RAM 预算间隙 | 4192 B | 4192 B |

净节省 **100 B**。尚未达到 4 KiB 应用增长余量目标；维持“不达标不合入”的约定，不据此推进 RTK。Flash 剩余是代码增长容量，不是运行中逐渐消耗的 RAM；本包不构成长期无溢出/无死机证明。

## 改动范围

只在 source-optimized 中修改 src/at_config.c、src/ec800m.c、src/f39_reply.c：紧凑固定串口命令名称表，共用查询结果/截断失败处理，TCP/UDP 同格式发送与关闭命令字符串共用。命令内容、参数范围、单位、配置保存、继电器安全条件、权限和 ACK/副作用顺序保留。

未修改 Makefile、编译选项、版本身份、Bootloader 源码/二进制、链接脚本、App 起址、内外 Flash 布局、OTA 验签/信任锚/包契约、BCR、factory/LKG/rollback 和持久化格式。生产目录的源码与默认构建产物均无本轮写入；哈希核对见 evidence/production-verification.json。核对期间主目录一个既有测试脚本由其他工作更新，本轮未改该文件，差异如实单列。

试验记录：广义参数 span/复制共用增加16 B，拒绝；数字读取共用增加64 B，拒绝；大端读取共用无净收益，拒绝；端点分支共用无净收益，拒绝。精简参数复制共用曾省32 B，但最坏栈增加8 B，已撤回。仅保留最终组合有益且 RAM/栈不恶化的三处源码改动。试验中间产物均为审计材料，不作为用户烧录入口。

## 文件与使用边界

- firmware/*-App.hex：仅 App，Intel HEX 已带 0x08006000 起址。
- firmware/*-App.bin：仅 App，加载地址 **0x08006000**；不能按0地址加载。
- firmware/*-App.elf / .map：与交付 BIN 绑定的调试及容量证据。
- firmware/*-OTA-UNSIGNED.bin：32 B 原契约传输头加同一 App，仅供后续平台签名/契约验证；**尚未签名，不可直接作为可安装 OTA 包，也不是可烧录 App BIN**。
- source-baseline：冻结时的完整构建输入副本（含原有未提交修改，不是 Git HEAD）。
- source-optimized：独立优化源码与验证工具；源码补丁 optimization.patch，测试环境修复 test-environment.patch。
- evidence：每项构建、门禁、测试、差分回放和哈希记录。

现有设备验证应保留原 Bootloader、配置及恢复镜像，不执行全片擦除；仅使用 App 对应的应用区更新流程。包内不提供 Combined/整片镜像。需要按设备现有启动契约验证安装、试运行确认及回退。

版本身份刻意冻结为 V3.094 / 3094，用于同输入尺寸比较。设备控制台不会显示另一个优化版本号，必须用本包路径和 SHA256 识别；已是3094的设备可能按正常版本策略拒绝同计数OTA。未修改平台或绕过版本校验，正式/远程试投前必须单独分配版本、重新构建和签名。

## 已自动验证与局限

ARM GNU Toolchain 14.3.Rel1 全量构建无编译警告，release-gate 通过；Flash门禁仍提示 LOW_HEADROOM。门禁内的历史容量参考配置不同，delta不可当作本轮收益；本轮收益只使用本包冻结基线106336 B对比。

{len(tests)} 项相关 host 测试通过且无 SKIP，覆盖 F39/串口/0x8300、JT808 参数、配置查询、EC800M、FOTA续传/掉电/验签和Boot旧镜像/LKG恢复等。6,244组F39和2,208组串口输入各覆盖保存成功/失败，每个版本16,904次执行逐字节对比一致；包含配置、应答及副作用/调用参数。它们是主机编译执行/模型/源码契约验证，不是实际 ARM 时序或实机运行证明。

初次 host 回归出现中文目录嵌入C代码时的ASCII编码异常、跨仓库配置路径缺失，以及冻结测试仍期望旧四参调用。仅在独立验证副本修复UTF-8/测试环境路径，并让调用契约严格包含当前真实第五个里程参数；未更改产品业务或放宽断言。修复补丁随包提供。

基线的参与编译文件已逐项核对原始SHA256。一个并行更新的测试夹具在环境修复后按原四参断言重建，未声称其原始混合换行字节已恢复；详情单列于baseline-snapshot-verification.json。这不涉及固件编译输入。

栈工具的独立报告仍为 INCOMPLETE（3个缺失帧、1个间接转移、29个尾转移、2个内部调用），项目已审查执行根RAM门禁通过。不能将其表述为全程序栈上界已证明。

**需要实机/HIL 验证**：出货旧Boot/旧App起点的OTA安装、确认、失败/掉电回滚；原定位、里程、主备平台、休眠、盲区与AGNSS混合负载；长期采集HEAP_USED、STK_PEAK、RAM_GAP和复位原因。只有你验收完成并明确授权后再考虑正式版本合入/发布。

## 独立复现

在 source-optimized 目录执行（MakeExe与ToolchainDir指向本机已安装工具）：

```powershell
& $MakeExe -j4 all -o include/build_version.h BUILD=build-common-final TOOLCHAIN_DIR=$ToolchainDir
& $MakeExe release-gate -o include/build_version.h BUILD=build-common-final TOOLCHAIN_DIR=$ToolchainDir
```

固定版本文件必须保留 `-o include/build_version.h`。以上只在源码副本生成产物，不应在主仓库执行本包试验命令。主机跨仓库身份测试如需执行，设置 A300_VALIDATION_WORKSPACE 为实际工作区根目录，或提供相同的只读平台配置证据。
'''
    (OUT/'README-测试说明.md').write_text(readme,encoding='utf-8')
    # Keep final delivery zip focused: clean source snapshots, final build
    # evidence and user-facing artifacts; trial binaries stay outside the zip.
    selected=[]
    for p in OUT.rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(OUT)
        if any(part.startswith('build') or part in ('__pycache__','.pytest_cache') for part in rel.parts[:-1]):continue
        selected.append(p)
    sums=''.join(digest(p)+'  '+p.relative_to(OUT).as_posix()+'\n' for p in sorted(selected) if p.name!='SHA256SUMS.txt')
    (OUT/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    selected=[p for p in selected if p.name!='SHA256SUMS.txt']+[OUT/'SHA256SUMS.txt']
    zip_path=OUT.parent/(OUT.name+'.zip')
    with zipfile.ZipFile(zip_path,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in selected:z.write(p,OUT.name+'/'+p.relative_to(OUT).as_posix())
    with zipfile.ZipFile(zip_path) as z:
        assert z.testzip() is None
        for line in sums.splitlines():
            sha,rel=line.split('  ',1)
            assert hashlib.sha256(z.read(OUT.name+'/'+rel)).hexdigest()==sha,rel
    zip_path.with_suffix('.zip.sha256').write_text(digest(zip_path)+'  '+zip_path.name+'\n',encoding='utf-8')
    print(json.dumps({'zip':str(zip_path),'zip_bytes':zip_path.stat().st_size,'sha256':digest(zip_path),'tests':len(tests),'changed':changes,'production_concurrent_changes':changed},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
