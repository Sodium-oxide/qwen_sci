const disciplineLabels: Record<string, string> = {
  "11": "农业与生物科学",
  "13": "生物化学、遗传学与分子生物学",
  "15": "化学工程",
  "16": "化学",
  "17": "计算机科学",
  "19": "地球与行星科学",
  "21": "能源",
  "22": "工程学",
  "23": "环境科学",
  "24": "免疫学与微生物学",
  "25": "材料科学",
  "26": "数学",
  "27": "医学",
  "28": "神经科学",
  "29": "护理学",
  "30": "药理学、毒理学与药剂学",
  "31": "物理学与天文学",
  "34": "兽医学",
  "35": "牙科学",
  "36": "健康专业",
};

export function disciplineLabel(id: string, fallback: string) {
  return disciplineLabels[id] || fallback;
}
