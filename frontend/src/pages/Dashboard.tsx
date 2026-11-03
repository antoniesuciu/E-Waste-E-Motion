import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Plus, BookOpen, Clock, Users, Play ,StopCircle, Loader2, Trash2} from 'lucide-react';
import GamepadController from '@/components/GamepadController';

interface Course {
  id: string;
  name: string;
  duration: number;
  robotCount: number;
  createdAt: string;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [runningCourseId, setRunningCourseId] = useState<string | null>(null);
  const [loadingCourseId, setLoadingCourseId] = useState<string | null>(null);
  const [editingCourseId, setEditingCourseId] = useState<string | null>(null);

  const handleCreateCourse = async () => {
    setCreating(true);
    try {
      const res = await fetch('/api/courses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Untitled', duration: 30 })
      });
      if (!res.ok) throw new Error('Create failed');
      const course = await res.json();
      navigate(`/create-course/${course.id}`);
    } catch (err) {
      console.error('Failed to create course:', err);
    } finally {
      setCreating(false);
    }
  };
  const fetchCourses = async () => {
    try {
      const response = await fetch('/api/courses');
      if (response.ok) {
        const data = await response.json();
        setCourses(data);
      }
    } catch (error) {
      console.error('Eroare in incarcarea traseelor:', error);
      // For demo purposes, add some mock data
      setCourses([
        {
          id: '1',
          name: 'Basic Formation',
          duration: 30,
          robotCount: 5,
          createdAt: '2025-01-15T10:00:00Z'
        },
        {
          id: '2',
          name: 'Advanced Choreography',
          duration: 45,
          robotCount: 8,
          createdAt: '2025-01-14T15:30:00Z'
        }
      ]);
    } finally {
      setLoading(false);
    }
  };
  
	useEffect(() => {
	  if (!runningCourseId) return;

	  let cancelled = false;
	  const poll = async () => {
	    try {
	      const res = await fetch(`/api/run/${runningCourseId}/status`);
	      if (!res.ok) throw new Error('status not ok');
	      const data = await res.json();
	      if (!data.running && !cancelled) {
		setRunningCourseId(null);
	      }
	    } catch (e) {
	      // Treat failures as "not running" to avoid stuck UI
	      if (!cancelled) setRunningCourseId(null);
	    }
	  };

	  // Check quickly, then every second
	  poll();
	  const id = setInterval(poll, 1000);

	  return () => { cancelled = true; clearInterval(id); };
	}, [runningCourseId]);

  useEffect(() => {
    fetchCourses();
  }, []);

  const formatTime = (minutes: number) => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  };

  const handleRunCourse = async (courseId: string) => {
    setLoadingCourseId(courseId);
    try {
      if (runningCourseId === courseId) {
        // stop
        await fetch(`/api/stop/${courseId}`, { method: 'POST' });
        setRunningCourseId(null);
      } else {
        // start
        await fetch(`/api/run/${courseId}`, { method: 'POST' });
        setRunningCourseId(courseId);
      }
    } catch (err) {
      console.error('Failed to toggle run state:', err);
    } finally {
      setLoadingCourseId(null);
    }
  };

	
  const handleEditCourse = async (courseId: string) => {
    setEditingCourseId(courseId);
    try {
      // prime server state: sets current_course + loads moves into memory
      const res = await fetch(`/api/course/edit/${courseId}/begin`, { method: 'POST' });
      if (!res.ok) throw new Error('begin-edit failed');
      // navigate once backend is ready
      navigate(`/create-course/${courseId}`);
    } catch (err) {
      console.error('Failed to begin edit:', err);
    } finally {
      setEditingCourseId(null);
    }
  };

  const handleDeleteCourse = async (courseId: string) => {
    try {
      await fetch(`/api/courses/${courseId}`, { method: 'DELETE' });
      setCourses(courses.filter(course => course.id !== courseId));
    } catch (error) {
      console.error('Failed to delete course:', error);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Course Management Section */}
      <div className="border-b border-border/50 bg-card/30 backdrop-blur">
        <div className="max-w-7xl mx-auto p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-2xl font-bold text-foreground mb-2">Trasee</h2>
              <p className="text-muted-foreground">Creati sau editati un nou traseu</p>
            </div>
            <Button 
              onClick={handleCreateCourse}
              className="flex items-center space-x-2 bg-gaming-primary hover:bg-gaming-primary/90"
            >
              <Plus className="h-4 w-4" />
              <span>Creati un traseu</span>
            </Button>
          </div>

          {/* Courses Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {loading ? (
              <div className="col-span-full text-center py-8 text-muted-foreground">
                Loading courses...
              </div>
            ) : courses.length === 0 ? (
              <div className="col-span-full text-center py-8">
                <BookOpen className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-medium text-foreground mb-2">Niciun traseu creat</h3>
                <p className="text-muted-foreground mb-4">Creati prima coregrafie pentru roboti</p>
                <Button 
                  onClick={handleCreateCourse}
                  variant="outline"
                  className="flex items-center space-x-2"
                >
                  <Plus className="h-4 w-4" />
                  <span>Creati primul traseu</span>
                </Button>
              </div>
            ) : (
              courses.map(course => (
                <Card key={course.id} className="border-border/50 bg-card/50 backdrop-blur hover:bg-card/70 transition-all">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-lg">{course.name}</CardTitle>
                      <Badge variant="secondary" className="bg-gaming-primary/20 text-gaming-primary">
                        Activ
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center space-x-2">
                          <Clock className="h-4 w-4 text-muted-foreground" />
                          <span>{formatTime(course.duration)}</span>
                        </div>
                        <div className="flex items-center space-x-2">
                          <Users className="h-4 w-4 text-muted-foreground" />
                          <span>{course.robotCount} robots</span>
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Created {formatDate(course.createdAt)}
                      </div>
                      <div className="flex space-x-2 pt-2">
			 <Button
			   size="sm"
			   variant="outline"
			   className="flex-1 flex items-center justify-center space-x-1"
			   onClick={() => handleEditCourse(course.id)}
			   disabled={editingCourseId === course.id}
			 >
			   {editingCourseId === course.id ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
			   <span>Edit</span>
			 </Button>
           		<Button
             		size="sm"
		            className="flex-1 flex items-center justify-center space-x-1"
		            onClick={() => handleRunCourse(course.id)}
		            disabled={loadingCourseId === course.id}
           		>
		            {loadingCourseId === course.id
		              ? <Loader2 className="h-3 w-3 animate-spin" />
			      : runningCourseId === course.id
				? <StopCircle className="h-3 w-3" />
				: <Play className="h-3 w-3" />
			    }
			    <span>
			      {runningCourseId === course.id ? 'Stop' : 'Go'}
			    </span>
			   </Button>
                        <Button 
                          size="sm" 
                          variant="destructive" 
                          className="w-10"
                          onClick={() => handleDeleteCourse(course.id)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Robot Controller Section */}
      <GamepadController />
    </div>
  );
}
