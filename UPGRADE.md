# v0.1 → 1.0 本地升级说明

此次从原始INT6181_FlightFinder_v0.1.zip继续开发；加入日期范围、多城市、可配置模拟满减和GUI联合查询，保留单程/往返、筛选、详情和CSV。没有删除原版文件，原始flights.json和数据生成器不变。

## 推荐：完整项目包

1. 备份当前PyCharm项目或在当前分支提交已有改动。
2. 将INT6181_FlightFinder_v1.0.zip解压到新目录，用PyCharm打开其中flight_finder。
3. 选择Python3.11+解释器，运行main.py；项目无需pip依赖，不需要EXE。
4. 确认后将项目文件复制到原Git工作目录，保留原来的.git、.idea、.venv，不要覆盖这些目录。

## 仅覆盖修改文件

如果本地确实仍是未修改的v0.1，可解压INT6181_FlightFinder_v1.0_changes.zip，把里面flight_finder目录下的**全部内容**覆盖到现有项目根目录（main.py所在目录），允许覆盖同名文件并显示隐藏目录，以便复制.github/workflows/tests.yml。不要再嵌套一层flight_finder，不要只复制main.py。补丁包含全部新增和修改文件，不能单独运行；有本地改动时先比对再合并，避免覆盖。

具体文件见docs/change_manifest.md。升级后data目录应同时有flights.json与discount.json。

## 本机验收与提交

```console
python main.py --check
python tools/run_tests.py --require-gui
python main.py
```

Windows上运行需要Tk与桌面；无显示导致跳过不算GUI验收。选择“灵活低价”，使用默认城市和日期、开启优惠、不限其他条件，应得69条、最低555元，且有5条有优惠。再检查标准往返、切换优惠、预算、无结果、日历、CSV和窗口缩放。

确认后提交到test，GitHub basic-check通过后按test→beta→master合并。master仅由组长操作。工作流只是自动检查，不自动发版、不发布到平台；保护master需要管理员另设仓库规则。此次没有替你连接或推送仓库。

首次本机测试后，如有课程要求变更，请同步代码、测试和文档。课程非代码提交清单见docs/submission_checklist.md。
