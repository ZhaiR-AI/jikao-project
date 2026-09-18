from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "真题英语短语"


# phrase || Chinese meaning || category || example || example translation
RAW_PHRASES = r"""
with sb leading the way|||由某人带路|||句型结构|||With the guide leading the way, we walked into the forest.|||在向导带路下，我们走进了森林。
set off on foot|||步行出发|||动词短语|||We set off on foot before sunrise.|||我们在日出前步行出发。
childish as sb may be|||尽管某人可能很幼稚|||让步句型|||Childish as he may be, he is kind to everyone.|||尽管他可能很幼稚，但他对每个人都很友善。
carry off|||成功完成；赢得|||动词短语|||The team carried off the first prize.|||这支队伍赢得了一等奖。
carry on|||继续|||动词短语|||Please carry on with your work.|||请继续你的工作。
carry away|||带走；使忘乎所以|||动词短语|||The beautiful music carried her away.|||优美的音乐使她陶醉。
carry out|||执行；实施|||动词短语|||The school will carry out a new plan.|||学校将实施一项新计划。
let sth proceed|||让某事继续进行|||句型结构|||The manager let the discussion proceed.|||经理让讨论继续进行。
not ... either|||也不|||句型结构|||I do not like the movie, and my sister does not either.|||我不喜欢这部电影，我妹妹也不喜欢。
talk to the other|||和另一个人交谈|||动词短语|||The two sides refused to talk to the other.|||双方拒绝和对方交谈。
a long time before|||过了很久才|||句型结构|||It was a long time before he understood the advice.|||过了很久他才明白这个建议。
affect one's plans|||影响某人的计划|||动词搭配|||Bad weather may affect our plans.|||坏天气可能会影响我们的计划。
be in charge of|||负责；掌管|||介词搭配|||She is in charge of the school library.|||她负责学校图书馆。
in response to|||作为对……的回应|||介词短语|||The company changed its policy in response to complaints.|||公司针对投诉改变了政策。
in relation to|||关于；与……有关|||介词短语|||The report explains the risks in relation to climate change.|||这份报告解释了与气候变化有关的风险。
in place of|||代替|||介词短语|||We used online classes in place of traditional lessons.|||我们用网课代替了传统课程。
go into details|||详细说明|||动词短语|||The speaker did not go into details.|||演讲者没有详细说明。
in particular|||尤其；特别|||介词短语|||I like fruit, apples in particular.|||我喜欢水果，尤其是苹果。
in general|||总的来说|||介词短语|||In general, the plan is practical.|||总的来说，这个计划很实用。
in short|||简言之|||介词短语|||In short, we need more time.|||简言之，我们需要更多时间。
in common|||共同；共有|||介词短语|||The two books have several ideas in common.|||这两本书有几个共同点。
except for|||除……之外|||介词短语|||The room is perfect except for its small window.|||除了窗户小之外，这个房间很完美。
instead of|||代替；而不是|||介词短语|||She walked instead of taking a taxi.|||她没有坐出租车，而是步行。
in addition to|||除了……还|||介词短语|||In addition to English, he studies French.|||除了英语，他还学习法语。
in spite of|||尽管|||介词短语|||In spite of the rain, the match continued.|||尽管下雨，比赛仍继续。
have no choice but to do sth|||除了做某事别无选择|||句型结构|||We had no choice but to wait.|||我们除了等待别无选择。
at least|||至少|||介词短语|||You should read at least ten pages a day.|||你每天至少应该读十页。
in no time|||立刻；很快|||介词短语|||The doctor will be here in no time.|||医生很快就会到。
at last|||终于|||介词短语|||At last, she found her lost keys.|||她终于找到了丢失的钥匙。
at present|||目前|||介词短语|||At present, I am preparing for an exam.|||目前我正在准备考试。
recover from|||从……中恢复|||动词短语|||It took him months to recover from the illness.|||他花了几个月才从疾病中恢复过来。
be superior to|||优于；比……好|||形容词搭配|||This material is superior to the old one.|||这种材料比旧材料好。
it is time to do sth|||是做某事的时候了|||句型结构|||It is time to review the lesson.|||是复习这节课的时候了。
be permitted to do sth|||被允许做某事|||被动结构|||Visitors are not permitted to enter this room.|||游客不被允许进入这个房间。
ever since|||自从……以来|||时间短语|||She has lived here ever since 2020.|||自2020年以来她一直住在这里。
one of the world's poorest countries|||世界上最贫穷的国家之一|||名词短语|||Nepal is one of the world's poorest countries.|||尼泊尔是世界上最贫穷的国家之一。
bring in|||赚取；带来|||动词短语|||The business brings in enough money each year.|||这项生意每年赚取足够的钱。
limit the number of|||限制……的数量|||动词搭配|||The school must limit the number of new students.|||学校必须限制新生人数。
issue a permit to|||向……发放许可证|||动词搭配|||The office issued a permit to the climber.|||办公室给这名登山者发放了许可证。
at one time|||曾经；一度|||时间短语|||At one time, this road was the only way to the village.|||这条路一度是去村庄的唯一道路。
the cost of|||……的费用|||名词短语|||The cost of the trip is higher than expected.|||这次旅行的费用比预期高。
lead sb to do sth|||导致某人做某事；引导某人做某事|||动词搭配|||The news led him to change his plan.|||这个消息使他改变了计划。
require sb to do sth|||要求某人做某事|||动词搭配|||The rules require students to wear uniforms.|||规定要求学生穿校服。
be physically fit|||身体健康；身体适合|||形容词搭配|||You must be physically fit for the job.|||你必须身体健康才能胜任这份工作。
have the strength to do sth|||有力气做某事|||动词搭配|||She did not have the strength to climb higher.|||她没有力气再往上爬。
suffer from|||遭受；患有|||动词短语|||Many people suffer from stress.|||许多人承受压力之苦。
be caused by|||由……造成|||被动结构|||The delay was caused by heavy traffic.|||延误是由交通拥堵造成的。
between A and B|||在A和B之间|||介词结构|||The village lies between the river and the hill.|||这个村庄位于河流和山丘之间。
be known as|||被称为；作为……而闻名|||被动结构|||The city is known as a center of art.|||这座城市被称为艺术中心。
stand on the top of|||站在……的顶部|||动词短语|||They stood on the top of the mountain.|||他们站在山顶。
be unprepared for|||没有为……做好准备|||形容词搭配|||Many students are unprepared for the difficult test.|||许多学生没有为这场难题做好准备。
job market|||就业市场|||名词短语|||The job market is changing quickly.|||就业市场正在快速变化。
close to zero|||接近于零|||介词短语|||The chance of rain is close to zero.|||下雨的可能性接近于零。
look for a job|||找工作|||动词短语|||He is looking for a job in the city.|||他正在城里找工作。
change careers|||改变职业|||动词短语|||Some people change careers in middle age.|||有些人在中年改变职业。
job growth|||就业增长|||名词短语|||Job growth has slowed this year.|||今年就业增长放缓了。
job turnover|||人员更替|||名词短语|||High job turnover can hurt a company.|||人员流动率高会损害公司。
due to|||由于|||介词短语|||The flight was delayed due to fog.|||航班因大雾延误。
in good times and bad|||无论顺境还是逆境|||介词短语|||True friends stay together in good times and bad.|||真正的朋友无论顺境逆境都在一起。
open up|||开放；出现（机会等）|||动词短语|||New opportunities open up every day.|||新的机会每天都会出现。
as it turns out|||结果证明；原来|||句型结构|||As it turns out, the answer was simple.|||结果证明，答案很简单。
have an impact on|||对……有影响|||动词搭配|||Sleep has an impact on your memory.|||睡眠会影响你的记忆力。
land a job|||成功获得工作|||动词短语|||She worked hard to land a job.|||她努力争取到了一份工作。
choose from|||从……中选择|||动词短语|||There are many courses to choose from.|||有许多课程可供选择。
compete for|||为争取……而竞争|||动词短语|||Several teams compete for the championship.|||几支队伍争夺冠军。
distinguish A from B|||区分A和B|||动词搭配|||Can you distinguish fact from opinion?|||你能区分事实和观点吗？
stay motivated|||保持动力|||动词搭配|||A clear goal helps you stay motivated.|||明确的目标能帮助你保持动力。
be willing to do sth|||愿意做某事|||形容词搭配|||She is willing to help her classmates.|||她愿意帮助同学。
identify one's skills|||确定某人的技能|||动词搭配|||The course helps students identify their skills.|||这门课程帮助学生了解自己的技能。
be creative about|||在……方面有创意|||形容词搭配|||Be creative about how you use your time.|||在利用时间方面要有创意。
present oneself to|||向……展示自己|||动词搭配|||He learned how to present himself to employers.|||他学会了如何向雇主展示自己。
potential employer|||潜在雇主|||名词短语|||Prepare questions for a potential employer.|||为潜在雇主准备一些问题。
keep going|||继续坚持|||动词短语|||Keep going even when the work is difficult.|||即使工作很难也要坚持下去。
give up|||放弃|||动词短语|||Do not give up after one failure.|||不要因为一次失败就放弃。
get hired|||被录用|||被动结构|||She got hired after the second interview.|||她在第二次面试后被录用了。
borrow money from|||从……借钱|||动词短语|||They had to borrow money from a bank.|||他们不得不从银行借钱。
take a mortgage|||办理抵押贷款|||动词短语|||The couple took a mortgage to buy a house.|||这对夫妇办理抵押贷款买房。
lend money|||借出钱|||动词短语|||Banks lend money to people who can repay it.|||银行把钱借给有能力偿还的人。
as much as|||多达；和……一样多|||介词短语|||The repair may cost as much as five hundred dollars.|||维修费用可能高达五百美元。
in other words|||换句话说|||介词短语|||In other words, we need a new plan.|||换句话说，我们需要一个新计划。
financial history|||财务记录|||名词短语|||The bank checked his financial history.|||银行查看了他的财务记录。
a good risk|||可靠的借款人；风险较小的人|||名词短语|||The bank believes she is a good risk.|||银行认为她是可靠的借款人。
kind of|||哪种；某种|||名词短语|||What kind of work do you enjoy?|||你喜欢哪种工作？
down payment|||首付款|||名词短语|||We saved for years to make the down payment.|||我们存了好几年钱才付得起首付款。
depend on|||取决于；依靠|||动词短语|||The final cost depends on the size.|||最终费用取决于大小。
save enough money|||存够钱|||动词短语|||They are trying to save enough money for college.|||他们正努力存够上大学的钱。
pay back|||偿还|||动词短语|||I will pay back the money next month.|||我下个月会还钱。
set off for|||出发前往|||动词短语|||The ship set off for America at dawn.|||船在黎明时出发前往美国。
set out to do sth|||开始努力做某事|||动词短语|||She set out to improve her English.|||她开始努力提高英语。
make sb blind|||使某人失明|||动词搭配|||The disease made him blind at an early age.|||这种疾病使他年幼时就失明了。
twice as large as|||是……的两倍大|||比较结构|||This room is twice as large as that one.|||这个房间是那个房间的两倍大。
the number of employees|||员工人数|||名词短语|||The number of employees has increased.|||员工人数增加了。
be characteristic of|||是……的特征|||形容词搭配|||Long winters are characteristic of this region.|||漫长的冬季是这个地区的特征。
one who|||……的人|||定语从句结构|||A good leader is one who listens carefully.|||优秀的领导者是善于认真倾听的人。
it is high time that sb did sth|||某人早该做某事了|||句型结构|||It is high time that we started the meeting.|||我们早该开始会议了。
show sb sth|||给某人看某物|||动词搭配|||Please show me your ticket.|||请给我看看你的票。
intermittent showers|||间歇性阵雨|||名词短语|||Intermittent showers are expected this afternoon.|||预计今天下午有间歇性阵雨。
as long as|||只要；和……一样长|||连词短语|||You may go as long as you finish your work.|||只要你完成工作就可以走。
have been doing sth|||一直在做某事|||时态结构|||They have been studying here for a year.|||他们已经在这里学习一年了。
a choice of|||对……的选择|||名词短语|||The course offers a choice of activities.|||这门课程提供多种活动选择。
which forms are most suitable|||哪些形式最合适|||疑问结构|||We must decide which forms are most suitable.|||我们必须决定哪些形式最合适。
close cooperation between A and B|||A和B之间的密切合作|||名词短语|||The project needs close cooperation between teachers and parents.|||这个项目需要教师和家长之间的密切合作。
where they occur|||它们发生的地方|||地点从句|||The report records where the problems occur.|||报告记录了问题发生的地方。
though written for children|||虽然是为儿童写的|||省略结构|||Though written for children, the story is interesting to adults.|||虽然是为儿童写的，这个故事对成年人也很有趣。
keep one's promise|||信守诺言|||动词搭配|||A good friend always keeps his promise.|||好朋友总是信守诺言。
have never been there|||从未去过那里|||完成时结构|||I have never been there before.|||我以前从未去过那里。
be slightly injured|||受了轻伤|||被动结构|||The driver was slightly injured in the accident.|||司机在事故中受了轻伤。
in favor of|||支持；赞成|||介词短语|||Most students are in favor of the new rule.|||大多数学生支持新规定。
in contrast to|||与……相比|||介词短语|||In contrast to his brother, he is very quiet.|||与他哥哥相比，他很安静。
in excess of|||超过；多于|||介词短语|||The repair cost was in excess of one thousand yuan.|||维修费用超过了一千元。
work well|||运转良好；奏效|||动词短语|||This method works well for beginners.|||这个方法对初学者很有效。
even though|||即使；尽管|||连词短语|||Even though it was late, she kept reading.|||尽管很晚了，她仍继续阅读。
at once|||立刻|||时间短语|||Please call me at once.|||请立即给我打电话。
perform tasks|||完成任务|||动词搭配|||The computer can perform several tasks at once.|||电脑可以同时完成几项任务。
at the same time|||同时|||时间短语|||Do not talk and write at the same time.|||不要同时说话和写字。
result in|||导致|||动词短语|||Too much stress can result in poor sleep.|||压力过大会导致睡眠质量差。
hand-held device|||手持设备|||名词短语|||A hand-held device can be useful for learning.|||手持设备对学习可能很有用。
attract attention|||吸引注意力|||动词搭配|||Bright colors attract attention.|||鲜艳的颜色能吸引注意力。
draw attention to|||把注意力吸引到……|||动词搭配|||The article draws attention to water pollution.|||这篇文章把注意力引向水污染。
at hand|||手头的；即将到来的|||介词短语|||We should solve the problem at hand first.|||我们应该先解决眼前的问题。
unfortunately|||不幸的是|||副词表达|||Unfortunately, the train was delayed.|||不幸的是，火车晚点了。
reward sb for|||因某事奖励某人|||动词搭配|||The teacher rewarded him for his hard work.|||老师因他的努力学习奖励了他。
feel better|||感觉好些|||动词搭配|||You will feel better after a good rest.|||好好休息后你会感觉好些。
since the appearance of|||自从……出现以来|||介词短语|||Since the appearance of smartphones, communication has changed.|||自从智能手机出现以来，交流方式发生了变化。
academic performance|||学习成绩；学业表现|||名词短语|||Sleep affects students' academic performance.|||睡眠会影响学生的学习成绩。
critical thinking skills|||批判性思维能力|||名词短语|||Reading improves critical thinking skills.|||阅读能提高批判性思维能力。
process information|||处理信息|||动词搭配|||The brain processes information very quickly.|||大脑处理信息非常快。
have difficulty doing sth|||做某事有困难|||句型结构|||Some children have difficulty making friends.|||一些孩子在交朋友方面有困难。
stick with|||坚持；继续做|||动词短语|||Stick with the plan for another week.|||再坚持这个计划一周。
tend to do sth|||倾向于做某事|||动词搭配|||People tend to remember bad news.|||人们往往会记住坏消息。
allow oneself to do sth|||允许自己做某事|||动词搭配|||Do not allow yourself to be distracted.|||不要让自己分心。
be distracted|||分心|||被动结构|||I was distracted by the noise.|||噪声使我分了心。
tune out|||不再注意；走神|||动词短语|||He tuned out during the long speech.|||长篇演讲期间他走神了。
switch over to|||转而使用；切换到|||动词短语|||She switched over to another website.|||她转而打开了另一个网站。
rather than|||而不是|||介词短语|||Read the book rather than watch television.|||读书而不是看电视。
in the long run|||从长远来看|||介词短语|||In the long run, patience will help you succeed.|||从长远来看，耐心会帮助你成功。
do poorly on|||在……方面表现差|||动词搭配|||He did poorly on the final test.|||他期末考试考得不好。
smile to show|||微笑以表示|||动词搭配|||People smile to show friendliness.|||人们微笑以表示友好。
body position|||身体姿势|||名词短语|||Your body position can change the meaning of a gesture.|||你的身体姿势可能改变手势的含义。
communicate with|||与……交流|||动词短语|||It is important to communicate with your children.|||和孩子交流很重要。
lean back|||向后靠|||动词短语|||He leaned back in his chair.|||他向后靠在椅子上。
lean forward|||向前倾|||动词短语|||She leaned forward to hear the speaker.|||她向前倾以听清演讲者的话。
keep a distance|||保持距离|||动词搭配|||Please keep a safe distance from the road.|||请和道路保持安全距离。
be interested in|||对……感兴趣|||形容词搭配|||He is interested in history.|||他对历史感兴趣。
listen to|||听；听从|||动词短语|||Listen to the teacher carefully.|||认真听老师讲课。
make sb think|||使某人认为|||动词搭配|||His silence made me think he was tired.|||他的沉默使我认为他累了。
cross one's arms|||交叉双臂|||动词短语|||She crossed her arms and waited.|||她交叉双臂等待。
look sb in the eye|||直视某人的眼睛|||动词短语|||Look the speaker in the eye when you answer.|||回答时要直视说话者的眼睛。
extend one's hand|||伸出某人的手|||动词短语|||He extended his hand in greeting.|||他伸手表示问候。
avoid mistakes|||避免错误|||动词搭配|||Check your work to avoid mistakes.|||检查作业以避免错误。
go wrong about|||对……产生误解|||动词短语|||We sometimes go wrong about our friends.|||我们有时会误解朋友。
a bit of|||一点；少量|||数量短语|||I need a bit of help.|||我需要一点帮助。
refer to|||指的是；提到|||动词短语|||What does this word refer to?|||这个词指的是什么？
based on|||基于；根据|||介词短语|||The decision was based on careful research.|||这个决定基于仔细的研究。
examine the meaning|||分析含义|||动词搭配|||We should examine the meaning of the message.|||我们应该分析这条信息的含义。
invite sb to|||邀请某人去……|||动词搭配|||She invited me to her birthday party.|||她邀请我参加她的生日聚会。
birthday party|||生日聚会|||名词短语|||We prepared a cake for her birthday party.|||我们为她的生日聚会准备了蛋糕。
make good use of time|||充分利用时间|||动词短语|||Make good use of your time before the exam.|||考试前要充分利用时间。
learn from failure|||从失败中学习|||动词搭配|||We should learn from failure instead of fearing it.|||我们应该从失败中学习，而不是害怕失败。
take a bus to|||乘公交车去……|||动词短语|||We took a bus to the museum.|||我们乘公交车去了博物馆。
do one's best|||尽某人最大努力|||动词短语|||Do your best and do not worry about the result.|||尽你最大努力，不要担心结果。
even if|||即使|||连词短语|||Even if you fail, you can try again.|||即使失败了，你也可以再试一次。
complain about|||抱怨；投诉|||动词短语|||Nobody will complain about your honest effort.|||没有人会抱怨你的努力。
be kind enough to do sth|||足够友善而做某事；劳驾做某事|||句型结构|||Would you be kind enough to help me?|||你能帮我一下吗？
get over|||从……中恢复；克服|||动词短语|||It took her time to get over the shock.|||她花了一段时间才从震惊中恢复过来。
get across|||使……被理解；传达|||动词短语|||A good teacher gets ideas across clearly.|||优秀的老师能清楚地传达观点。
arise|||出现；产生|||动词|||New problems may arise during the project.|||项目期间可能会出现新问题。
while|||尽管；然而|||连词|||While your idea is useful, it needs more evidence.|||尽管你的想法有用，但还需要更多证据。
put off|||推迟；拖延|||动词短语|||Do not put off your homework until tomorrow.|||不要把作业拖到明天。
a popular belief that|||一种普遍的看法，即……|||名词结构|||There is a popular belief that practice makes perfect.|||有一种普遍看法认为熟能生巧。
be said to have done sth|||据说已经做过某事|||句型结构|||The book is said to have been translated into many languages.|||据说这本书已经被翻译成多种语言。
convey one's ideas|||表达某人的想法|||动词搭配|||He uses simple words to convey his ideas.|||他用简单的词表达自己的想法。
all you need is|||你所需要的就是|||句型结构|||All you need is a good rest.|||你所需要的就是好好休息。
in view of|||鉴于；考虑到|||介词短语|||In view of the weather, we canceled the trip.|||考虑到天气，我们取消了旅行。
in the end|||最后；最终|||介词短语|||In the end, hard work paid off.|||最终，努力得到了回报。
other things being equal|||在其他条件相同的情况下|||独立主格结构|||Other things being equal, the cheaper option is better.|||在其他条件相同的情况下，便宜的选择更好。
put on|||穿上；上演|||动词短语|||She put on a bright red dress.|||她穿上了一条鲜红色的裙子。
there is no use doing sth|||做某事没有用|||句型结构|||There is no use arguing with him.|||和他争论没有用。
much as|||尽管很……|||让步句型|||Much as I like the plan, I cannot accept it.|||尽管我很喜欢这个计划，但我不能接受它。
have drunk|||已经喝过|||完成时结构|||Having drunk the coffee, he washed the cup.|||喝完咖啡后，他洗了杯子。
despite|||尽管|||介词短语|||Despite the difficulty, she continued studying.|||尽管困难，她仍继续学习。
further one's study|||深造；继续学业|||动词搭配|||He went abroad to further his study.|||他出国深造。
were I in your position|||如果我是你|||虚拟语气|||Were I in your position, I would refuse the offer.|||如果我是你，我会拒绝这个提议。
be promoted by|||被……晋升|||被动结构|||He was promoted by his employer last year.|||他去年被雇主晋升了。
without a car|||没有汽车|||介词短语|||Without a car, traveling is less convenient.|||没有汽车，出行就不太方便。
feel poor|||感到贫穷|||动词搭配|||People may feel poor without enough freedom.|||没有足够的自由，人们可能会感到贫乏。
start doing sth|||开始做某事|||动词搭配|||He started making cars in large numbers.|||他开始大量生产汽车。
on wheels|||在轮子上；乘车|||介词短语|||The new system put the town on wheels.|||新系统让这个城镇的交通运转起来。
help to do sth|||帮助做某事|||动词搭配|||Exercise helps to improve your health.|||锻炼有助于改善健康。
after all|||毕竟；终究|||介词短语|||After all, everyone makes mistakes.|||毕竟，每个人都会犯错。
first of all|||首先|||介词短语|||First of all, read the instructions.|||首先，阅读说明。
move around|||四处移动；到处走动|||动词短语|||A car allows people to move around freely.|||汽车让人们可以自由出行。
provide sth for sb|||为某人提供某物|||动词搭配|||The school provides free books for students.|||学校为学生提供免费书籍。
offer sth to sb|||向某人提供某物|||动词搭配|||The hotel offers free breakfast to guests.|||酒店为客人提供免费早餐。
without doing sth|||没有做某事|||介词结构|||You cannot improve without practicing.|||不练习就无法提高。
as ... as|||和……一样……|||比较结构|||This exercise is as useful as the last one.|||这个练习和上一个一样有用。
in other parts of the world|||在世界其他地区|||介词短语|||The custom is common in other parts of the world.|||这种习俗在世界其他地区很常见。
be provided by|||由……提供|||被动结构|||The service is provided by the local government.|||这项服务由当地政府提供。
too ... to do sth|||太……而不能做某事|||句型结构|||The box is too heavy to carry.|||这个箱子太重，搬不动。
spirit of independence|||独立精神|||名词短语|||The spirit of independence helped the country grow.|||独立精神帮助这个国家发展。
neither ... nor ...|||既不……也不……|||并列结构|||He speaks neither English nor French.|||他既不会说英语也不会说法语。
follow a schedule|||遵循时间表|||动词搭配|||I do not like to follow a strict schedule.|||我不喜欢遵循严格的时间表。
freedom to do sth|||做某事的自由|||名词结构|||Everyone needs the freedom to choose.|||每个人都需要选择的自由。
mobile communication technology|||移动通信技术|||名词短语|||Mobile communication technology connects people quickly.|||移动通信技术使人们快速联系起来。
short message|||短信；简短信息|||名词短语|||I sent him a short message.|||我给他发了一条短信。
transmit sth between A and B|||在A和B之间传输某物|||动词搭配|||The system transmits data between phones and computers.|||这个系统在手机和电脑之间传输数据。
cell phone|||手机|||名词短语|||Please turn off your cell phone.|||请关掉手机。
violate one's privacy|||侵犯某人的隐私|||动词搭配|||The message may violate your privacy.|||这条信息可能侵犯你的隐私。
take measures to do sth|||采取措施做某事|||动词搭配|||The city took measures to reduce pollution.|||这座城市采取措施减少污染。
get permission to do sth|||获得做某事的许可|||动词搭配|||You need to get permission to enter.|||你需要获得进入许可。
for nothing|||免费；白费|||介词短语|||He promised to repair it for nothing.|||他答应免费修理它。
pay attention to|||注意|||动词短语|||Please pay attention to the spelling.|||请注意拼写。
well-designed|||设计精良的|||形容词|||The well-designed package attracts buyers.|||设计精良的包装吸引买家。
have nothing to do with|||与……没有关系|||句型结构|||The mistake has nothing to do with you.|||这个错误与你没有关系。
plain package|||普通包装；简易包装|||名词短语|||A plain package may cost less.|||普通包装可能花费更少。
according to|||根据；按照|||介词短语|||According to the report, prices will rise.|||根据报告，价格将会上涨。
thank sb for doing sth|||感谢某人做某事|||动词搭配|||Thank you for inviting me.|||谢谢你邀请我。
fail to do sth|||未能做某事|||动词搭配|||He failed to catch the train.|||他没能赶上火车。
catch a train|||赶火车|||动词短语|||We hurried to catch the train.|||我们赶紧去赶火车。
on time|||准时|||介词短语|||The bus arrived on time.|||公交车准时到达。
no matter what|||无论什么|||让步结构|||No matter what happens, stay calm.|||无论发生什么，都要保持冷静。
be angry with|||生某人的气|||形容词搭配|||She was not angry with me.|||她没有生我的气。
be sure|||确定；确信|||形容词搭配|||I am not sure whether he will come.|||我不确定他是否会来。
arrive at|||到达（小地点）|||动词短语|||She arrived at school on time.|||她准时到达学校。
wait anxiously|||焦急地等待|||动词搭配|||The parents waited anxiously outside.|||父母在外面焦急地等待。
raise the curtain|||拉开帷幕|||动词短语|||The audience became quiet as they raised the curtain.|||帷幕拉开时观众安静下来。
lose one's balance|||失去平衡|||动词短语|||He lost his balance on the wet floor.|||他在湿地板上失去了平衡。
be convenient for|||对……方便|||形容词搭配|||Is Friday convenient for you?|||星期五对你方便吗？
used to do sth|||过去常常做某事|||句型结构|||I used to get up early.|||我过去常常早起。
get used to doing sth|||习惯于做某事|||句型结构|||She is getting used to living alone.|||她正在习惯独自生活。
struggle with|||与……斗争；艰难应对|||动词短语|||He struggled with his conscience.|||他进行着良心上的挣扎。
more precious than|||比……更珍贵|||比较结构|||Time is more precious than money.|||时间比金钱更珍贵。
be exposed through|||通过……被揭露|||被动结构|||The truth was exposed through the press.|||真相通过媒体被揭露。
walk in the dark|||在黑暗中行走|||动词短语|||Do not walk in the dark without a light.|||没有灯不要在黑暗中行走。
sound like|||听起来像|||系动词搭配|||That sounds like a good idea.|||那听起来是个好主意。
as a result|||结果；因此|||介词短语|||He forgot the map and, as a result, got lost.|||他忘了地图，因此迷路了。
fall ill|||生病|||动词短语|||She fell ill during the trip.|||她旅行期间生病了。
drop one's grades|||使成绩下降|||动词搭配|||Lack of sleep can drop your grades.|||睡眠不足会使你的成绩下降。
be difficult to grasp|||难以理解|||形容词结构|||The idea is difficult to grasp at first.|||这个想法起初很难理解。
believe it or not|||信不信由你|||插入语|||Believe it or not, he finished the work in an hour.|||信不信由你，他一小时就完成了工作。
remember doing sth|||记得做过某事|||动词结构|||I remember meeting her before.|||我记得以前见过她。
remember to do sth|||记得要做某事|||动词结构|||Remember to lock the door.|||记得锁门。
excuse sb for doing sth|||原谅某人做某事|||动词搭配|||Please excuse me for being late.|||请原谅我迟到了。
break in|||插话；闯入|||动词短语|||I am sorry to break in, but I have news.|||抱歉打断一下，但我有消息。
lose one's temper|||发脾气|||动词短语|||Try not to lose your temper.|||尽量不要发脾气。
any other|||任何其他的|||限定词结构|||This building is taller than any other building nearby.|||这座建筑比附近其他任何建筑都高。
the moment|||一……就……|||连词短语|||The moment I saw him, I knew he was upset.|||我一看到他，就知道他很难过。
make sb do sth|||使某人做某事|||使役结构|||The story made me change my mind.|||这个故事使我改变了想法。
contribute to|||有助于；促成|||动词短语|||Exercise contributes to good health.|||锻炼有助于身体健康。
volunteer teacher|||志愿教师|||名词短语|||The volunteer teacher helped the children read.|||志愿教师帮助孩子们阅读。
participate in|||参加|||动词短语|||Many students participated in the project.|||许多学生参加了这个项目。
take a seat|||坐下|||动词短语|||Please take a seat at the back.|||请坐在后面。
in the back of|||在……的后面|||介词短语|||He sat in the back of the room.|||他坐在房间后面。
show no sign of|||没有……的迹象|||动词搭配|||The child showed no sign of stopping.|||这个孩子没有要停下来的迹象。
walk down|||沿着……走|||动词短语|||I walked down the row of desks.|||我沿着一排书桌走过去。
arouse curiosity|||引起好奇心|||动词搭配|||The strange noise aroused my curiosity.|||奇怪的声音引起了我的好奇心。
be busy doing sth|||忙于做某事|||形容词结构|||She is busy preparing for the test.|||她正忙于准备考试。
get sb to do sth|||让某人做某事|||动词搭配|||The teacher got the students to work together.|||老师让学生们一起学习。
parents' meeting|||家长会|||名词短语|||The parents' meeting will start at seven.|||家长会将在七点开始。
interrupt sb|||打断某人|||动词搭配|||Please do not interrupt the speaker.|||请不要打断演讲者。
be instructed to do sth|||被指示做某事|||被动结构|||The students were instructed to fold the paper.|||学生们被指示把纸折叠起来。
fold sth in half|||把某物对折|||动词搭配|||Fold the paper in half.|||把纸对折。
bring sth to the front|||把某物带到前面|||动词搭配|||Bring your answer sheet to the front.|||把答题纸拿到前面。
dig a hole|||挖洞|||动词短语|||They dug a hole in the garden.|||他们在花园里挖了一个洞。
at the bottom of|||在……底部|||介词短语|||The box was at the bottom of the hole.|||盒子在洞底。
join hands|||手拉手；联合|||动词短语|||The children joined hands in a circle.|||孩子们手拉手围成一圈。
raise one's head|||抬起头|||动词短语|||He raised his head and smiled.|||他抬起头笑了。
honor the memory of|||纪念……|||动词搭配|||We gathered to honor the memory of the teacher.|||我们聚在一起纪念这位老师。
be replaced by|||被……取代|||被动结构|||The old system was replaced by a new one.|||旧系统被新系统取代了。
rest in peace|||安息|||固定表达|||May she rest in peace.|||愿她安息。
turn around|||转身；转过来|||动词短语|||He turned around and walked back.|||他转身走了回来。
march back|||列队走回|||动词短语|||The students marched back to the classroom.|||学生们列队走回教室。
on rare occasions|||在极少数情况下|||介词短语|||On rare occasions, the machine stops working.|||极少数情况下，这台机器会停止工作。
remind sb of|||使某人想起|||动词短语|||This song reminds me of my childhood.|||这首歌使我想起童年。
get along with|||与……相处融洽|||动词短语|||Does your dog get along with other pets?|||你的狗和其他宠物相处得好吗？
fit the environment|||适应环境|||动词搭配|||Choose a pet that fits the environment.|||选择适合环境的宠物。
be demanding|||要求高；难伺候|||形容词|||A dog is a demanding pet.|||狗是一种需要很多照顾的宠物。
look after|||照顾|||动词短语|||Who will look after the children?|||谁来照顾孩子？
under three months old|||不到三个月大|||年龄表达|||The puppy is under three months old.|||这只小狗不到三个月大。
form a relationship with|||与……建立关系|||动词搭配|||Children form a relationship with their teachers.|||孩子们会和老师建立关系。
be noted for|||因……而闻名|||形容词搭配|||The city is noted for its history.|||这座城市因历史而闻名。
social work|||社会工作|||名词短语|||She devoted her life to social work.|||她把一生奉献给社会工作。
make a contribution to|||为……作出贡献|||动词搭配|||Everyone can make a contribution to society.|||每个人都能为社会作出贡献。
civil-rights movement|||民权运动|||名词短语|||She made a contribution to the civil-rights movement.|||她为民权运动作出了贡献。
infer from|||从……推断|||动词短语|||What can we infer from the passage?|||我们能从文章中推断出什么？
be a pioneer|||成为先驱|||名词结构|||These women were pioneers in their fields.|||这些女性是各自领域的先驱。
take notice of|||注意到|||动词短语|||He took no notice of my warning.|||他没有注意我的警告。
to a certain extent|||在一定程度上|||介词短语|||I agree with you to a certain extent.|||在一定程度上我同意你的看法。
survive the earthquake|||在地震中幸存|||动词搭配|||Few houses survived the earthquake.|||很少有房屋在地震中幸存下来。
ask for advice|||征求建议|||动词短语|||Do not hesitate to ask for advice.|||不要犹豫，尽管征求建议。
may not recognize|||可能认不出|||情态结构|||He has changed so much that you may not recognize him.|||他变化很大，你可能认不出他。
the number of members|||成员人数|||名词短语|||The number of members reached two hundred.|||成员人数达到两百人。
to one's surprise|||令某人惊讶的是|||介词短语|||To my surprise, he remembered my name.|||令我惊讶的是，他记得我的名字。
so ... a ...|||如此……的一个……|||句型结构|||It is so useful a book that I read it twice.|||这是一本如此有用的书，我读了两遍。
the more ..., the more ...|||越……越……|||比较句型|||The more you practice, the more confident you become.|||你练习得越多，就越自信。
with pleasure|||乐意效劳|||固定表达|||Could you help me? With pleasure.|||你能帮我吗？乐意效劳。
convince sb to do sth|||说服某人做某事|||动词搭配|||She convinced me to try again.|||她说服我再试一次。
persuade sb to do sth|||劝说某人做某事|||动词搭配|||He persuaded his friend to study harder.|||他劝朋友更加努力学习。
look like|||看起来像|||动词短语|||What does the museum look like?|||博物馆看起来是什么样的？
in case|||以防；如果|||介词短语|||Take an umbrella in case it rains.|||带把伞以防下雨。
suggest that sb do sth|||建议某人做某事|||虚拟语气|||The teacher suggested that we make a study plan.|||老师建议我们制订学习计划。
however + adjective|||无论多么……|||让步结构|||However difficult the task is, keep trying.|||无论任务多么困难，都要继续尝试。
in balance|||处于平衡状态|||介词短语|||The ecosystem is in balance.|||生态系统处于平衡状态。
out of balance|||失去平衡|||介词短语|||Too much hunting puts nature out of balance.|||过度捕猎使自然失去平衡。
introduce a species|||引入一个物种|||动词搭配|||Introducing a foreign species may harm the ecosystem.|||引入外来物种可能损害生态系统。
balance of nature|||自然平衡|||名词短语|||Human actions can disturb the balance of nature.|||人类行为可能扰乱自然平衡。
upset the ecology|||破坏生态|||动词搭配|||Pollution can upset the ecology of a lake.|||污染会破坏湖泊生态。
a short span of time|||一小段时间|||名词短语|||The forest disappeared in a short span of time.|||森林在很短时间内消失了。
any other living creature|||其他任何生物|||名词短语|||No other living creature has changed the planet so much.|||没有其他生物如此改变过地球。
with no thought for|||完全不考虑……|||介词短语|||He used the resources with no thought for the future.|||他使用资源时完全没有考虑未来。
put matters right|||纠正问题；挽回局面|||动词短语|||We must act now to put matters right.|||我们必须现在行动来纠正问题。
too late|||太迟|||形容词短语|||It may already be too late to repair the damage.|||修复损害可能已经太迟了。
lie in the hands of|||掌握在……手中|||动词短语|||The future lies in the hands of young people.|||未来掌握在年轻人手中。
the sooner ..., the better|||越早……越好|||比较句型|||The sooner we start, the better.|||我们越早开始越好。
the cause of|||……的原因|||名词短语|||Lack of sleep is a cause of poor concentration.|||睡眠不足是注意力不集中的原因之一。
at an ever-increasing rate|||以不断增加的速度|||介词短语|||The population is growing at an ever-increasing rate.|||人口正以不断增加的速度增长。
use up|||用光；耗尽|||动词短语|||We must not use up all the natural resources.|||我们不能耗尽所有自然资源。
be unable to provide|||无法提供|||动词搭配|||The land is unable to provide enough food.|||土地无法提供足够的食物。
turn into|||变成|||动词短语|||The fertile land turned into a desert.|||肥沃的土地变成了沙漠。
fertile land|||肥沃的土地|||名词短语|||Farmers need fertile land to grow food.|||农民需要肥沃的土地来种植粮食。
save up|||攒钱；储蓄|||动词短语|||She is saving up for a new computer.|||她正在攒钱买新电脑。
satisfy one's hunger|||满足某人的饥饿|||动词搭配|||A small meal can satisfy your hunger.|||一顿小餐可以满足你的饥饿感。
grow dissatisfied with|||逐渐对……不满意|||形容词搭配|||People grow dissatisfied with unfair treatment.|||人们逐渐对不公平的待遇感到不满。
physical satisfaction|||身体上的满足|||名词短语|||Food and shelter provide physical satisfaction.|||食物和住所带来身体上的满足。
by the end of|||到……结束时|||介词短语|||By the end of the year, we had saved enough money.|||到年底时，我们已经存够了钱。
live in poverty|||生活贫困|||动词短语|||Many families still live in poverty.|||许多家庭仍生活贫困。
at the age of|||在……岁时|||介词短语|||She started school at the age of four.|||她四岁时开始上学。
early education|||早期教育|||名词短语|||Early education can help disadvantaged children.|||早期教育能帮助处境不利的儿童。
solve social problems|||解决社会问题|||动词搭配|||Education cannot solve all social problems alone.|||教育不能单独解决所有社会问题。
two years of|||两年的……|||数量结构|||Two years of practice changed his skills.|||两年的练习改变了他的技能。
with sb's help|||在某人的帮助下|||介词短语|||With his help, my English improved greatly.|||在他的帮助下，我的英语进步很大。
make great progress|||取得很大进步|||动词搭配|||She has made great progress in English.|||她在英语方面取得了很大进步。
as important as|||和……一样重要|||比较结构|||Protecting nature is as important as developing the economy.|||保护自然和发展经济一样重要。
it is getting late|||天色渐晚；时间不早了|||句型结构|||It is getting late, so we should go home.|||天色渐晚了，所以我们应该回家。
be time to go home|||该回家了|||句型结构|||I think it is time to go home.|||我想我们该回家了。
if there is a chance|||如果有机会|||条件表达|||If there is a chance, I will visit the museum.|||如果有机会，我会参观博物馆。
attend a party|||参加聚会|||动词短语|||I cannot attend the party tonight.|||我今晚不能参加聚会。
prepare for an exam|||准备考试|||动词短语|||He is preparing for an exam.|||他正在准备考试。
grab the chance|||抓住机会|||动词短语|||Grab the chance to practice speaking.|||抓住机会练习口语。
become a doctor|||成为医生|||动词短语|||She hopes to become a doctor.|||她希望成为一名医生。
save millions of lives|||拯救数百万人的生命|||动词搭配|||Vaccines can save millions of lives.|||疫苗可以拯救数百万人的生命。
have colonies|||拥有殖民地|||动词短语|||The country once had colonies overseas.|||这个国家曾经在海外拥有殖民地。
by telephone|||通过电话|||介词短语|||You can report the problem by telephone.|||你可以通过电话报告问题。
report a non-emergency|||报告非紧急情况|||动词搭配|||People can report a non-emergency by telephone.|||人们可以通过电话报告非紧急情况。
seek ways to improve|||寻找改进的方法|||动词搭配|||The team is seeking ways to improve the app.|||团队正在寻找改进应用程序的方法。
take action|||采取行动|||动词短语|||The government must take action now.|||政府必须现在采取行动。
live a better life|||过更好的生活|||动词短语|||The policy helps people live a better life.|||这项政策帮助人们过上更好的生活。
realize one's dreams|||实现某人的梦想|||动词搭配|||Hard work helps people realize their dreams.|||努力帮助人们实现梦想。
not as ... as|||不如……|||比较结构|||Life was not as comfortable as it is today.|||那时的生活不如现在舒适。
trust sb|||信任某人|||动词短语|||If we trust him, he will work hard.|||如果我们信任他，他会努力工作。
low-carbon life|||低碳生活|||名词短语|||Walking to work is part of a low-carbon life.|||步行上班是低碳生活的一部分。
cut down forests|||砍伐森林|||动词搭配|||People should stop cutting down forests.|||人们应该停止砍伐森林。
water pollution|||水污染|||名词短语|||Water pollution threatens many fish.|||水污染威胁着许多鱼类。
air pollution|||空气污染|||名词短语|||Air pollution is a serious problem.|||空气污染是一个严重问题。
start with|||从……开始|||动词短语|||A healthy lifestyle can start with small changes.|||健康的生活方式可以从小改变开始。
make full use of|||充分利用|||动词短语|||We should make full use of every sheet of paper.|||我们应该充分利用每一张纸。
save water|||节约用水|||动词短语|||Turn off the tap to save water.|||关掉水龙头来节约用水。
call on sb to do sth|||号召某人做某事|||动词搭配|||The teacher called on us to protect the environment.|||老师号召我们保护环境。
join in|||参加；加入|||动词短语|||More people should join in the campaign.|||更多人应该加入这项活动。
"""


def parse_phrases() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_line in RAW_PHRASES.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split("|||")
        if len(fields) != 5:
            raise ValueError(f"短语数据格式错误：{line}")
        phrase, meaning, category, example, translation = fields
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "phrase": phrase,
                "meaning": meaning,
                "category": category,
                "example": example,
                "translation": translation,
            }
        )
    return items


def load_exam_words() -> set[str]:
    """Load the five exam files so the output is tied to the local true-exam set."""
    import json

    words: set[str] = set()
    for index in range(1, 6):
        paths = sorted((ROOT / "data" / "papers").glob(f"*-{index}.json"))
        if not paths:
            continue
        data = json.loads(paths[0].read_text(encoding="utf-8"))
        for section in data.get("sections", []):
            for question in section.get("questions", []):
                words.add(str(question.get("stem") or ""))
                for option in question.get("options", []):
                    words.add(str(option.get("text") or ""))
            for group in section.get("groups", []):
                words.add(str(group.get("description") or ""))
    return words


def write_output(items: list[dict[str, str]]) -> None:
    category_order = [
        "动词短语",
        "动词搭配",
        "介词短语",
        "形容词搭配",
        "名词短语",
        "句型结构",
        "被动结构",
        "时态结构",
        "比较结构",
        "让步句型",
        "连词短语",
        "虚拟语气",
        "并列结构",
        "副词表达",
        "动词",
        "形容词",
        "年龄表达",
        "固定表达",
    ]
    order = {category: number for number, category in enumerate(category_order)}
    items.sort(key=lambda item: (order.get(item["category"], 99), item["phrase"].casefold()))

    lines: list[str] = []
    for item in items:
        lines.extend(
            [
                item["phrase"],
                f"|||{item['meaning']}|||{item['category']}|||{item['example']}|||{item['translation']}|||",
                "",
            ]
        )
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    items = parse_phrases()
    if len(load_exam_words()) == 0:
        raise SystemExit("未找到五套真题数据，未生成文件。")
    write_output(items)
    print(f"已生成：{OUTPUT}")
    print(f"短语数量：{len(items)}")


if __name__ == "__main__":
    main()
