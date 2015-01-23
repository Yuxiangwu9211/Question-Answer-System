import webapp2
import jinja2
import os
import urllib
import re
import cgi
import time

from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.api import images

JINJA_ENVIRONMENT = jinja2.Environment(
	loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
	extensions=['jinja2.ext.autoescape'],
	autoescape=True)

HOST_PATH='http://qc319-final\.appspot\.com'

def render_str(template, **params):
	t = JINJA_ENVIRONMENT.get_template(template)
	return t.render(params)

def is_owner(user):
	if users.User(user) != users.get_current_user():
		return False;
	else:
		return True;

#main page which views all the questions

class Mainpage(webapp2.RequestHandler):
	def get(self):        
		self.query = {}
		self.user = users.get_current_user()
		self.users = users
		self.response.write(render_str('Top.html', p = self))
		

		#used to display only 10 question one page
		fetch = self.request.get('fetch')
		if not fetch:
			fetch = 0
		fetch = int(fetch)
		self.query['fetch'] = int(fetch)

		#displayed by the reverse order of time
		posts = Question.all().order('-create_time')
		self.tags = sorted(set([j for i in posts for j in i.tags]))
		search_tag = self.request.get('tag')
		self.query['search_tag'] = search_tag
		if search_tag:
			posts.filter('tags', search_tag)
		self.response.write(render_str('searchTag.html', p = self))

		#when goint to the next page, increase fetch by 10
		self.root_path = self.request.url.split('?')[0]
		next_page_query = self.query.copy()
		next_page_query['fetch'] += 10

		#a help function to get the new url of next page
		self.next_page_url = self.gen_url(self.root_path, next_page_query)
		#when reach the last 10 questions, no more next pages displayed
		
		if fetch+10 >= posts.count():
			self.last_page = True
		for post in posts [fetch:fetch+10]:
			self.response.write(post.render())
			#if image exists, then display it
			if post.avatar:
				self.response.out.write('<div style="padding-left:300px; max-width:500px"><img style="height:300px; width:400px" src="/img?img_id=%s"></img></div><br>' %
                        	post.key())
		# used for creating new question fuction
		if self.user:
			self.response.write(render_str('createNewQuestion.html', p = self))
		# used to view the next page
		self.response.write(render_str('nextPage.html', p = self))
		self.response.write(render_str('Bottom.html', p = self))

	#a help function to get the new url of next page
	def gen_url(self, root, query):
		return root + '?' + '&'.join(['{0}={1}'.format(k, q) for (k, q) in query.items() if q])
        
		
#enter questions with answers
class ViewAnswer(webapp2.RequestHandler):
	def get(self, question_id):
		self.query = {}
		self.user = users.get_current_user()
		self.users = users
		# display the top part of Answer interface
		self.response.write(render_str('Top.html', p = self))

		# get the question name from the database
		question=Question.get_by_id(int(question_id))
		
		self.response.write(question.render(True, question_id))

		#get the answers related to the question from the database
		answers=db.GqlQuery('select * from Answer where question_id = :1 order by answervote desc', question_id)
		for answer in answers:
			self.response.write(answer.render())
		
		#create a new answer
		self.parent=question_id
		if self.user:
			self.response.write(render_str('CreateNewAnswer.html', p = self))

		self.response.write(render_str('Bottom.html', p = self))

		
# database to store information about question and a render function to generate one block represent one question

# question database, used to store all the related info about each question
class Question(db.Model):
	user = db.UserProperty()
	body = db.TextProperty()
	tags = db.StringListProperty()
	avatar = db.BlobProperty()
	create_time = db.DateTimeProperty(auto_now_add = True)
	last_modified = db.DateTimeProperty(auto_now = True)
	has_modified = db.BooleanProperty()

	#display question
	def render(self, render_full_text=False, question_id=None):
		# if question content displayed in the main page exceed the length of 500, then display the exceeded part with ...(more)...
		if len(self.body) > 50 and not render_full_text:
			self.render_text = self.body[:50].replace('\n', '<br>') + ' ... (more) ...'
		else:
			self.render_text = self.body.replace('\n', '<br>')

		# if some content start with http://, then displayed it as a link
		http = r'(https?://\w[^ \t<]*)'
		img_pattern = r'\.(png|jpg|gif)$'
		img = re.compile(img_pattern)
		local_img = re.compile(r'(localhost:\d+/pic/[^/ ]+)|({0}/pic/[^/ ]+)'.format(HOST_PATH))
		links = re.findall(http, self.render_text)

		# all the links could be redirected to that url
		for link in links:
		    if img.search(link) or local_img.search(link):
		        self.render_text = re.sub(r'({0})'.format(link), r'<a href="\1"><img src="\1" alt="Image"></a>', self.render_text)
		    else:
		        self.render_text = re.sub(r'({0})'.format(link), r'<a href="\1"> \1 </a>', self.render_text)            
		
		qid = str(self.key().id())
		votes = db.GqlQuery('select * from QuestionVote where question_id = :1', qid)
		
		#compute the count of the value sum of vote
		sumVote = 0
		for value in votes:
			sumVote = sumVote + value.vote
		self.sumVote=sumVote
		#when log out, 'up' and 'down' buttons are not displayed
		self.currentUser = users.get_current_user()

		# judge whether it is the main page based on the question_id
		if question_id==None:
			self.mainpage=True
		else:
			self.mainpage=False

		# if the user is the current user, he is allowed to edit the question
		if self.user == users.get_current_user():
			self.is_editable = True
		return render_str('OneQuestionBlock.html', p = self)
	
	def render_RSS(self):
		return render_str('rssContent.html', p=self)

#edit question
class EditQuestion(webapp2.RequestHandler):    
	def get(self, question_id):        
		user = users.get_current_user()

		self.query = {}
		self.user = users.get_current_user()
		self.users = users
		self.response.write(render_str('Top1.html', p = self))

		question = Question.get_by_id(int(question_id))
		self.response.write(self.render(question))

		self.response.write(render_str('Bottom.html', p = self))


	# used to display the content in the textarea in the next page
	def render(self, p=None):
		if p:
			p.body_str = p.body
		else:
			class p: pass
			p.body_str = ''

		return render_str('EditQuestion.html', p=p)

# use the same html as edit question
class NewQuestion(EditQuestion):
	def get(self):

		self.query = {}
		self.user = users.get_current_user()
		self.users = users
		self.response.write(render_str('Top1.html', p = self))

		self.response.write(self.render())
		self.response.write(render_str('Bottom.html', p = self))


#handle create new question, save it to database
class QuestionSave(webapp2.RequestHandler):
	def post(self, question_id=None):
		if not question_id:
			post = Question()
			post.user = users.get_current_user()
		else:
			# TODO Check if the blog post is oiwned by the current user
			post = Question.get_by_id(int(question_id))
			post.has_modified = True

		#save the image to database
		avatar = self.request.get('img')
		if avatar:
			post.avatar = db.Blob(avatar)

		#get the content from the form and save it to database
		post.body = self.request.get('body')
		post.tags = self.request.get('tags').split()

		post.put()

		# used for wait the database to refreash
		time.sleep(0.1)
		self.redirect('/')

#answer database
class Answer(db.Model):
	user = db.UserProperty()
	question_id = db.StringProperty()
	body = db.TextProperty()
	create_time = db.DateTimeProperty(auto_now_add = True)
	last_modified = db.DateTimeProperty(auto_now = True)
	has_modified = db.BooleanProperty()
	answervote = db.IntegerProperty()

	#display answer block
	def render(self, render_full_text=False):
		# if question content displayed in the main page exceed the length of 500, then display the exceeded part with ...(more)...
		if len(self.body) > 500 and not render_full_text:
			self.render_text = self.body[:500].replace('\n', '<br>') + ' ... (more) ...'
		else:
			self.render_text = self.body.replace('\n', '<br>')

		# if some content start with http://, then displayed it as a link
		http = r'(https?://\w[^ \t<]*)'
		img_pattern = r'\.(png|jpg|gif)$'
		img = re.compile(img_pattern)

		
		local_img = re.compile(r'(localhost:\d+/pic/[^/ ]+)|({0}/pic/[^/ ]+)'.format(HOST_PATH))
		links = re.findall(http, self.render_text)

		# all the links could be redirected to that url
		for link in links:
		    if img.search(link) or local_img.search(link):
		        self.render_text = re.sub(r'({0})'.format(link), r'<a href="\1"><img src="\1" alt="Image"></a>', self.render_text)
		    else:
		        self.render_text = re.sub(r'({0})'.format(link), r'<a href="\1"> \1 </a>', self.render_text)            
		
		aid = str(self.key().id())
		votes = db.GqlQuery('select * from AnswerVote where question_id = :1 and answer_id = :2', self.question_id, aid)

		#compute the count of the value sum of vote
		sumVote = 0
		for vote in votes:
			sumVote = sumVote+vote.vote
		self.sumVote=sumVote
		

		#check if it is current user
		self.currentUser = users.get_current_user()

		if not render_full_text:
			self.show_permalink = True
		if self.user == users.get_current_user():
			self.is_editable = True
		return render_str('OneAnswerBlock.html', p = self)

	#refresh votes
	def refresh(self, question_id, answer_id):
		votes = db.GqlQuery('select * from AnswerVote where question_id = :1 and answer_id = :2', question_id, answer_id)
		sumVote = 0
		for vote in votes:
			sumVote = sumVote+vote.vote
		self.sumVote=sumVote

#question vote database
class QuestionVote(db.Model):
	user = db.UserProperty()
	question_id = db.StringProperty()
	vote = db.IntegerProperty()

#answer vote database
class AnswerVote(db.Model):
	user = db.UserProperty()
	question_id = db.StringProperty()
	answer_id = db.StringProperty()
	vote = db.IntegerProperty()

#edit answer
class EditAnswer(webapp2.RequestHandler):    
	def get(self, question_id, answer_id):
		self.query = {}
		self.user = users.get_current_user()
		self.users = users
		self.response.write(render_str('Top1.html', p = self))
		
		answer = Answer.get_by_id(int(answer_id))
		self.response.write(self.render(question_id, answer))


	#save content to display in the next page
	def render(self, question_id, p=None):
		if p:
			p.body_str = p.body
			p.parent=question_id
		else:
			class p: pass
			p.body_str = ''
			p.parent=question_id

		return render_str('EditAnswer.html', p=p)

#reuse the edit answer page
class NewAnswer(EditAnswer):
	def get(self, question_id):
		self.query = {}
		self.user = users.get_current_user()
		self.users = users
		self.response.write(render_str('Top1.html', p = self))
		self.response.write(self.render(question_id))

#handle submitted answer and save it to database
class AnswerSave(webapp2.RequestHandler):
	def post(self, question_id, answer_id=None):
		if not answer_id:
			post = Answer()
			post.user = users.get_current_user()
		else:
			# TODO Check if the blog post is oiwned by the current user
			post = Answer.get_by_id(int(answer_id))
			post.has_modified = True

		#save answer related info into the database
		post.body = self.request.get('body')
		post.question_id=question_id
		post.answervote=0

		key = post.put()

		# memcache.delete(KEY)
		#        self.redirect('/{0}'.format(key.id()))
		time.sleep(0.1)
		self.redirect('/'+question_id)

#handle suiation of vote question
class VoteQuestion(webapp2.RequestHandler):
	def get(self, question_id):
		user = users.get_current_user()
		action = self.request.get('action')
		
		q = db.GqlQuery('select * from QuestionVote where user = :1 and question_id = :2', user, question_id)
		if q.count() > 0:
			for result in q:
				result.delete()

		#store the new vote infomation into the database
		value = QuestionVote()
		value.user = user
		value.question_id = question_id
		if action == "up" or action == "upMainPage":
			value.vote = 1
		else:
			value.vote = -1

		value.put()
		#allow time to refresh the database
		time.sleep(0.1)

		if action.find('MainPage') == -1:
			self.redirect('/'+question_id)
		else:
			self.redirect('/')

#handle suiation of vote answer
class VoteAnswer(webapp2.RequestHandler):
	def get(self, question_id, answer_id):
		user = users.get_current_user()
		action = self.request.get_all('action')
		action = action[0]

		q = db.GqlQuery('select * from AnswerVote where user = :1 and question_id = :2 and answer_id = :3', user, question_id, answer_id)
		if q.count() > 0:
			for result in q:
				result.delete()
		
		value = AnswerVote()
		value.user = user
		value.question_id = question_id
		value.answer_id = answer_id
		#vote up
		if action == "up":
			value.vote = 1
		#vote down
		else:
			value.vote = -1
		value.put()
		#allow time to refresh the database
		time.sleep(0.1)

		#store the new vote infomation into the database
		answer = Answer.get_by_id(int(answer_id))
		answer.refresh(question_id, answer_id)
		answer.put()
		#allow time to refresh the database
		time.sleep(0.1)
		self.redirect('/'+question_id)

#handler the case of RSS reference
class RSSHandler(webapp2.RequestHandler):
	def get(self):
		posts = Question.all().order('-create_time')
		#        self.response.write(render_str('rss_sample.html', p=self))

		self.response.write(render_str('rssHeader.html', p=self))
		for post in posts:
			self.response.write(post.render_RSS())
		self.response.write(render_str('rssFoot.html', p=self))

#handler the case of image upload
class Image(webapp2.RequestHandler):
    def get(self):
        greeting = db.get(self.request.get('img_id'))
        if greeting.avatar:
            self.response.headers['Content-Type'] = 'image/png'
            self.response.out.write(greeting.avatar)
        else:
            self.error(404)

app = webapp2.WSGIApplication([
	('/', Mainpage),
	('/RSS', RSSHandler),
	('/post', QuestionSave),
	('/img', Image),
	('/createquestion', NewQuestion),
	('/(\\d+)', ViewAnswer),
	('/(\\d+)/post', QuestionSave),
	('/(\\d+)/createanswer', NewAnswer),
	('/(\\d+)/(\\d+)/answerpost', AnswerSave),
	('/(\\d+)/answerpost', AnswerSave),
	('/(\\d+)/vote', VoteQuestion),
	('/(\\d+)/(\\d+)/vote', VoteAnswer),
	('/(\\d+)/edit', EditQuestion),
	('/(\\d+)/(\\d+)/edit', EditAnswer),

], debug=True)